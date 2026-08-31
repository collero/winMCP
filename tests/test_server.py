"""Tests for server.py — the FastMCP app that registers the three Outlook
calendar tools and serves them over stdio.

Phase 8: Server Wiring (mcp-server-bootstrap spec)
"""
import asyncio
import importlib
import json
import shutil
import subprocess
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest
import yaml
from fastmcp import Client
from fastmcp.exceptions import ToolError

from models.schemas import EventDetail, FileDetail, PageDetail
from tools.fake_adapter import FakeCalendarAdapter
from tools.fake_file_search_adapter import FakeFileSearchAdapter
from tools.fake_mail_adapter import FakeMailAdapter
from tools.fake_onenote_adapter import FakeOneNoteAdapter
from tools.fake_task_adapter import FakeTaskAdapter
from tools.onenote_adapter import NotebookNode, SectionNode

_ALL_TOOL_NAMES = {
    "calendar_search",
    "calendar_get_event",
    "calendar_get_notes",
    "task_search",
    "task_get_task",
    "mail_search",
    "mail_get_message",
    "file_search",
    "file_get_info",
    "onenote_search",
    "onenote_get_page",
    "onenote_list_sections",
    "onenote_list_pages",
    "onenote_create_page",
    "onenote_update_page",
    "server_info",
}


def test_import_succeeds_without_win32com(mocker):
    mocker.patch.dict(sys.modules)
    sys.modules.pop("win32com", None)
    sys.modules.pop("win32com.client", None)

    import server

    importlib.reload(server)

    assert "win32com" not in sys.modules
    assert "win32com.client" not in sys.modules
    # Phase 6: server.py now also imports tools.task_adapter (for the
    # TaskPort type + lazy real-adapter resolver) at module level; that
    # import path must be exercised here too and still not pull in
    # win32com, since tools/task_adapter.py only imports it lazily inside
    # OutlookTaskAdapter's own methods.
    assert "tools.task_adapter" in sys.modules
    # outlook-mail-read Phase 6: server.py now also imports
    # tools.mail_adapter (for the MailPort type + lazy real-adapter
    # resolver) at module level; that import path must be exercised here
    # too and still not pull in win32com, since tools/mail_adapter.py only
    # imports it lazily inside OutlookMailAdapter's own methods.
    assert "tools.mail_adapter" in sys.modules
    # file-search Phase 5: server.py now also imports
    # tools.file_search_adapter (for the FileSearchPort type + lazy
    # real-adapter resolver) at module level; that import path must be
    # exercised here too and still not pull in win32com, since
    # tools/file_search_adapter.py only imports win32com/pythoncom lazily
    # inside WindowsSearchAdapter._dispatch_connection().
    assert "tools.file_search_adapter" in sys.modules
    # add-onenote-adapter Phase 9: server.py now also imports
    # tools.onenote_adapter (for the OneNotePort type + lazy real-adapter
    # resolver) at module level; that import path must be exercised here
    # too and still not pull in win32com — OneNoteAdapter never imports
    # win32com at all (it talks to OneNote exclusively via the
    # PsBridgeTransport-driven powershell.exe/COM bridge, never
    # win32com.client directly).
    assert "tools.onenote_adapter" in sys.modules


def test_server_name_is_win_mcp():
    """The FastMCP app must be named "win-mcp" (renamed from
    "outlook-calendar-mcp"); this is what Claude Desktop/smoke tests see as
    serverInfo.name over the wire."""
    import server

    app = server.create_server(adapter=FakeCalendarAdapter(events=[]))

    assert app.name == "win-mcp"


def test_all_three_tools_registered():
    import server

    fake = FakeCalendarAdapter(events=[])
    app = server.create_server(adapter=fake)

    async def _list_names():
        async with Client(app) as client:
            tools = await client.list_tools()
            return {tool.name for tool in tools}

    names = asyncio.run(_list_names())

    assert names == _ALL_TOOL_NAMES


def test_task_tools_registered():
    """Phase 6: task_search/task_get_task must be registered alongside the
    three calendar tools when a FakeTaskAdapter is injected via the new
    `task_adapter` create_server() parameter."""
    import server

    fake_calendar = FakeCalendarAdapter(events=[])
    fake_tasks = FakeTaskAdapter(tasks=[])
    app = server.create_server(adapter=fake_calendar, task_adapter=fake_tasks)

    async def _list_names():
        async with Client(app) as client:
            tools = await client.list_tools()
            return {tool.name for tool in tools}

    names = asyncio.run(_list_names())

    assert names == _ALL_TOOL_NAMES


def test_mail_tools_registered():
    """outlook-mail-read Phase 6: mail_search/mail_get_message must be
    registered alongside the three calendar tools and two task tools when a
    FakeMailAdapter is injected via the new `mail_adapter` create_server()
    parameter."""
    import server

    fake_calendar = FakeCalendarAdapter(events=[])
    fake_mail = FakeMailAdapter(inbox=[])
    app = server.create_server(adapter=fake_calendar, mail_adapter=fake_mail)

    async def _list_names():
        async with Client(app) as client:
            tools = await client.list_tools()
            return {tool.name for tool in tools}

    names = asyncio.run(_list_names())

    assert names == _ALL_TOOL_NAMES


def test_mail_search_tool_returns_results_via_fake_mail_adapter():
    """End-to-end mail_search call via FastMCP's in-process Client, mirroring
    test_task_search_tool_returns_results_via_fake_task_adapter — confirms
    request->adapter->response wiring, not just registration."""
    import server
    from models.schemas import MessageDetail

    now = datetime.now(timezone.utc)
    message = MessageDetail(
        entry_id="MSG-1",
        subject="Factura agosto",
        sender="Ana Gomez",
        sender_address="ana.gomez@example.com",
        date=now - timedelta(hours=1),
        has_attachments=False,
        body="Adjunto la factura.",
        to=["yo@example.com"],
    )
    fake_mail = FakeMailAdapter(inbox=[message])
    app = server.create_server(mail_adapter=fake_mail)

    async def _call():
        async with Client(app) as client:
            return await client.call_tool(
                "mail_search", {"folder": "inbox", "subject": "factura"}
            )

    result = asyncio.run(_call())

    assert result.data.results[0].entryId == "MSG-1"
    assert result.data.resultsTruncated is False


def test_mail_search_tool_explicit_limit_bounds_and_flags_truncated(mocker):
    """search-result-caps (BUG-002): `mail_search` accepts an explicit
    `limit` argument end-to-end, bounding the response and flagging
    `resultsTruncated`."""
    import server
    from models.schemas import MessageDetail

    mocker.patch("tools.settings.load_settings", return_value={})
    now = datetime.now(timezone.utc)
    messages = [
        MessageDetail(
            entry_id=f"MSG-{i}",
            subject="Factura agosto",
            sender="Ana Gomez",
            sender_address="ana.gomez@example.com",
            date=now - timedelta(hours=i),
            has_attachments=False,
            body="",
            to=[],
        )
        for i in range(10)
    ]
    fake_mail = FakeMailAdapter(inbox=messages)
    app = server.create_server(mail_adapter=fake_mail)

    async def _call():
        async with Client(app) as client:
            return await client.call_tool(
                "mail_search", {"folder": "inbox", "subject": "factura", "limit": 3}
            )

    result = asyncio.run(_call())

    assert len(result.data.results) == 3
    assert result.data.resultsTruncated is True


def test_mail_search_tool_non_positive_limit_surfaces_invalid_request_tool_error():
    import server

    fake_mail = FakeMailAdapter(inbox=[])
    app = server.create_server(mail_adapter=fake_mail)

    async def _call():
        async with Client(app) as client:
            return await client.call_tool(
                "mail_search", {"folder": "inbox", "subject": "x", "limit": 0}
            )

    with pytest.raises(ToolError, match="invalid_request"):
        asyncio.run(_call())


def test_mail_search_tool_folder_path_returns_results_via_fake_mail_adapter():
    """mail-reading-depth Phase 7 (server wiring amendment): `mail_search`
    must accept an optional `folderPath` argument end-to-end (no `folder`
    given at all), wired through to `MailSearchRequest.folder_path` and
    resolved by `FakeMailAdapter`'s `folder_paths` dict — mirrors
    test_mail_search_tool_returns_results_via_fake_mail_adapter's shape for
    the new selector."""
    import server
    from models.schemas import MessageDetail

    now = datetime.now(timezone.utc)
    message = MessageDetail(
        entry_id="MSG-FP-1",
        subject="Proyecto 2026 kickoff",
        sender="Ana Gomez",
        sender_address="ana.gomez@example.com",
        date=now - timedelta(hours=1),
        has_attachments=False,
        body="Cuerpo",
        to=["yo@example.com"],
    )
    fake_mail = FakeMailAdapter(folder_paths={"Proyectos/2026": [message]})
    app = server.create_server(mail_adapter=fake_mail)

    async def _call():
        async with Client(app) as client:
            return await client.call_tool(
                "mail_search", {"folderPath": "Proyectos/2026", "subject": "kickoff"}
            )

    result = asyncio.run(_call())

    assert result.data.results[0].entryId == "MSG-FP-1"


def test_mail_search_tool_both_folder_and_folder_path_surfaces_clean_tool_error():
    """Both selectors given at once must surface as a clean `ToolError` via
    the existing `_map_error` `ValueError`/`ValidationError` path (pydantic's
    `ValidationError` is a `ValueError` subclass — `MailSearchRequest`'s
    `_exactly_one_folder_selector` validator fires) — not an uncaught crash
    or a raw FastMCP framework error."""
    import server

    fake_mail = FakeMailAdapter(inbox=[])
    app = server.create_server(mail_adapter=fake_mail)

    async def _call():
        async with Client(app) as client:
            return await client.call_tool(
                "mail_search",
                {"folder": "inbox", "folderPath": "Proyectos/2026", "subject": "x"},
            )

    with pytest.raises(ToolError, match="invalid_request"):
        asyncio.run(_call())


def test_mail_search_tool_folder_path_unresolved_returns_mail_folder_not_found_error():
    """A `folderPath` that does not resolve must surface cleanly through
    `_map_error`'s existing `CalendarToolError` base-class catch (no
    explicit `MailFolderNotFoundError` branch needed in `_map_error`) —
    asserts the `mail_folder_not_found` code reaches the caller, not a
    crash or a generic error."""
    import server

    fake_mail = FakeMailAdapter(folder_paths={})
    app = server.create_server(mail_adapter=fake_mail)

    async def _call():
        async with Client(app) as client:
            return await client.call_tool(
                "mail_search", {"folderPath": "Nope/Missing", "subject": "x"}
            )

    with pytest.raises(ToolError, match="mail_folder_not_found"):
        asyncio.run(_call())


def test_mail_get_message_tool_include_html_body_returns_html_body():
    """`mail_get_message` must accept an optional `includeHtmlBody`
    argument (default False) and thread it through to
    `GetMessageRequest.include_html_body` -> `adapter.get_message(...,
    include_html=True)`, returning the seeded `htmlBody`."""
    import server
    from models.schemas import MessageDetail

    now = datetime.now(timezone.utc)
    message = MessageDetail(
        entry_id="MSG-HTML-1",
        subject="Factura",
        sender="Ana Gomez",
        sender_address="ana.gomez@example.com",
        date=now,
        has_attachments=False,
        body="texto plano",
        to=["yo@example.com"],
        html_body="<p>texto plano</p>",
    )
    fake_mail = FakeMailAdapter(inbox=[message])
    app = server.create_server(mail_adapter=fake_mail)

    async def _call():
        async with Client(app) as client:
            return await client.call_tool(
                "mail_get_message", {"entryId": "MSG-HTML-1", "includeHtmlBody": True}
            )

    result = asyncio.run(_call())

    assert result.data.htmlBody == "<p>texto plano</p>"


def test_mail_get_message_tool_default_omits_html_body_backward_compatible():
    """Backward-compat guard: an existing-shape call with no
    `includeHtmlBody` argument at all must still work and must NOT return
    the seeded HTML body — mirrors the tools/mail.py-layer backward-compat
    test from Batch 1, one layer up at the server boundary."""
    import server
    from models.schemas import MessageDetail

    now = datetime.now(timezone.utc)
    message = MessageDetail(
        entry_id="MSG-HTML-2",
        subject="Factura",
        sender="Ana Gomez",
        sender_address="ana.gomez@example.com",
        date=now,
        has_attachments=False,
        body="texto plano",
        to=["yo@example.com"],
        html_body="<p>texto plano</p>",
    )
    fake_mail = FakeMailAdapter(inbox=[message])
    app = server.create_server(mail_adapter=fake_mail)

    async def _call():
        async with Client(app) as client:
            return await client.call_tool("mail_get_message", {"entryId": "MSG-HTML-2"})

    result = asyncio.run(_call())

    assert result.data.htmlBody is None


def test_mail_adapter_selection_deferred_when_win32com_unavailable(mocker):
    """Mirrors test_task_adapter_selection_deferred_when_win32com_unavailable
    for the mail adapter path: import + server construction must succeed
    even though win32com is genuinely unavailable; only the actual
    mail_search call should fail, with a clear error - not an import-time
    or construction-time crash."""
    mocker.patch.dict(sys.modules)
    sys.modules.pop("win32com", None)
    sys.modules.pop("win32com.client", None)

    import server

    app = server.create_server()  # no mail_adapter injected -> real lazy adapter

    async def _call():
        async with Client(app) as client:
            return await client.call_tool("mail_search", {"folder": "inbox", "subject": "x"})

    with pytest.raises(ToolError):
        asyncio.run(_call())


def test_file_search_tools_registered_via_fake_file_search_adapter():
    """Phase 5: file_search/file_get_info must be registered alongside the
    calendar/task/mail tools when a FakeFileSearchAdapter is injected via
    the new `file_search_adapter` create_server() parameter — mirrors
    test_mail_tools_registered's shape."""
    import server

    fake_calendar = FakeCalendarAdapter(events=[])
    fake_file_search = FakeFileSearchAdapter(files=[])
    app = server.create_server(adapter=fake_calendar, file_search_adapter=fake_file_search)

    async def _list_names():
        async with Client(app) as client:
            tools = await client.list_tools()
            return {tool.name for tool in tools}

    names = asyncio.run(_list_names())

    assert names == _ALL_TOOL_NAMES


def test_file_search_tool_returns_results_via_fake_file_search_adapter(mocker):
    """End-to-end file_search call via FastMCP's in-process Client, mirroring
    test_mail_search_tool_returns_results_via_fake_mail_adapter's shape.
    Uses a `phrase` query (rather than `filename`) so the call actually
    routes through the injected `FakeFileSearchAdapter` — file-search-
    resilience's Phase 5 dispatch split answers a `filename`-only query
    entirely via the filesystem walk instead, which would find nothing
    for a synthetic Windows path on this host. `tools.file_search.load_settings`
    is mocked so the containment/post-call filter has a deterministic
    non-empty allowed_roots regardless of this host's environment (a bare
    `USERPROFILE`-less Linux CI host would otherwise resolve
    `default_search_roots()` to `[]`, which would drop every result via
    the post-call defense-in-depth filter). Asserts against the
    `FileSearchResponse` envelope's `results` field (Phase 5/6's wiring of
    the response shape), not a bare list."""
    import server

    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\Users\\ana"]},
    )
    file_ = FileDetail(
        path="C:\\Users\\ana\\Documents\\Report.docx",
        name="Report.docx",
        size=1024,
        last_modified=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
        created_time=datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc),
        snippet="quarterly figures",
    )
    fake_file_search = FakeFileSearchAdapter(files=[file_])
    app = server.create_server(file_search_adapter=fake_file_search)

    async def _call():
        async with Client(app) as client:
            return await client.call_tool("file_search", {"phrase": "quarterly"})

    result = asyncio.run(_call())

    assert result.data.results[0].name == "Report.docx"
    assert result.data.resultsTruncated is False


def test_file_search_tool_no_filters_surfaces_invalid_request_tool_error(mocker):
    """`file_search` with neither filename nor phrase must surface the
    tool layer's plain `ValueError` as an `[invalid_request]` ToolError."""
    import server

    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\Users\\ana"]},
    )
    fake_file_search = FakeFileSearchAdapter(files=[])
    app = server.create_server(file_search_adapter=fake_file_search)

    async def _call():
        async with Client(app) as client:
            return await client.call_tool("file_search", {})

    with pytest.raises(ToolError, match="invalid_request"):
        asyncio.run(_call())


def test_file_search_tool_out_of_root_scope_surfaces_search_root_not_allowed_error(mocker):
    """An out-of-root `scope` must surface `SearchRootNotAllowedError` as a
    `[search_root_not_allowed]` ToolError, before any adapter call."""
    import server

    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\Users\\ana"]},
    )
    fake_file_search = FakeFileSearchAdapter(files=[])
    app = server.create_server(file_search_adapter=fake_file_search)

    async def _call():
        async with Client(app) as client:
            return await client.call_tool(
                "file_search", {"filename": "x", "scope": "D:\\Shared"}
            )

    with pytest.raises(ToolError, match="search_root_not_allowed"):
        asyncio.run(_call())


def test_file_get_info_tool_returns_detail_via_fake_file_search_adapter(mocker):
    """End-to-end file_get_info call via FastMCP's in-process Client.
    Phase 5 rewired `file_get_info` to source its core facts from
    `os.stat` first (never the index) — `os.stat` is mocked here so a
    synthetic Windows path resolves on this Linux test host, then the
    injected `FakeFileSearchAdapter` supplies the `snippet` enrichment."""
    import server

    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\Users\\ana"]},
    )
    mocker.patch(
        "tools.file_search.os.stat",
        return_value=types.SimpleNamespace(
            st_size=1024,
            st_mtime=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc).timestamp(),
            st_ctime=datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc).timestamp(),
        ),
    )
    file_ = FileDetail(
        path="C:\\Users\\ana\\Documents\\Report.docx",
        name="Report.docx",
        size=1024,
        last_modified=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
        created_time=datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc),
        snippet="quarterly figures",
    )
    fake_file_search = FakeFileSearchAdapter(files=[file_])
    app = server.create_server(file_search_adapter=fake_file_search)

    async def _call():
        async with Client(app) as client:
            return await client.call_tool(
                "file_get_info", {"path": "C:\\Users\\ana\\Documents\\Report.docx"}
            )

    result = asyncio.run(_call())

    assert result.data.snippet == "quarterly figures"


def test_file_get_info_tool_nonexistent_path_surfaces_path_not_found_error(mocker):
    """Phase 6 (task 6.1): a path that does not resolve on disk must
    surface `PathNotFoundError` as a `[path_not_found]` ToolError — the
    file-get-info spec's ADDED "Path Not Found On Disk" requirement. No
    `os.stat` mock is needed: this synthetic Windows path genuinely does
    not exist on the Linux test host, so the real `os.stat` call already
    raises `FileNotFoundError` on its own."""
    import server

    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\Users\\ana"]},
    )
    fake_file_search = FakeFileSearchAdapter(files=[])
    app = server.create_server(file_search_adapter=fake_file_search)

    async def _call():
        async with Client(app) as client:
            return await client.call_tool(
                "file_get_info", {"path": "C:\\Users\\ana\\Missing.docx"}
            )

    with pytest.raises(ToolError, match="path_not_found"):
        asyncio.run(_call())


def test_file_search_adapter_selection_deferred_when_win32com_unavailable(mocker):
    """Mirrors test_mail_adapter_selection_deferred_when_win32com_unavailable
    for the file-search adapter path: import + server construction must
    succeed even though win32com is genuinely unavailable; only the actual
    file_search call should fail, with a clear error - not an import-time
    or construction-time crash. Uses a `phrase` query (not `filename`) so
    the call actually reaches the real, win32com-backed adapter chain —
    Phase 5's dispatch split answers `filename`-only queries via the
    filesystem walk, which never touches win32com at all."""
    mocker.patch.dict(sys.modules)
    sys.modules.pop("win32com", None)
    sys.modules.pop("win32com.client", None)
    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\Users\\ana"]},
    )

    import server

    app = server.create_server()  # no file_search_adapter injected -> real lazy adapter

    async def _call():
        async with Client(app) as client:
            return await client.call_tool("file_search", {"phrase": "x"})

    with pytest.raises(ToolError):
        asyncio.run(_call())


def test_file_search_tool_filename_only_walks_real_filesystem_under_unindexed_scope(tmp_path, mocker):
    """Phase 7 integration test (task 7.3): `file_search {"filename": ".md",
    "scope": <unindexed dir>}` end-to-end via `create_server()` with a
    fake adapter that would raise if ever called — the closest feasible
    stand-in for the live Windows acceptance scenario (an unindexed root
    like `C:\\usr`/`C:\\co`), since real win32com/PowerShell access is not
    runnable on WSL2. Exercises the real `tools.file_search_walk.walk_filename`
    against a real temp directory tree, proving `filename` search succeeds
    without the index."""
    import server

    (tmp_path / "notes.md").write_text("hello")
    (tmp_path / "notes.txt").write_text("hello")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "more.md").write_text("hello")

    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": [str(tmp_path)]},
    )

    class _NeverCalledAdapter:
        def search(self, filename, phrase, roots, top_n):
            raise AssertionError("adapter must never be called for a filename-only query")

        def get_info(self, path_or_url):
            raise AssertionError("adapter must never be called for a filename-only query")

    app = server.create_server(file_search_adapter=_NeverCalledAdapter())

    async def _call():
        async with Client(app) as client:
            return await client.call_tool(
                "file_search", {"filename": ".md", "scope": str(tmp_path)}
            )

    result = asyncio.run(_call())

    names = {r.name for r in result.data.results}
    assert names == {"notes.md", "more.md"}
    assert result.data.resultsTruncated is False


def test_task_search_tool_returns_results_via_fake_task_adapter():
    import server
    from models.schemas import TaskDetail, TaskStatus

    task = TaskDetail(
        entry_id="T1",
        subject="Renovar licencia",
        due_date=None,
        status=TaskStatus.IN_PROGRESS,
        is_complete=False,
        body="notas",
    )
    fake_tasks = FakeTaskAdapter(tasks=[task])
    app = server.create_server(task_adapter=fake_tasks)

    async def _call():
        async with Client(app) as client:
            return await client.call_tool("task_search", {"subject": "renovar"})

    result = asyncio.run(_call())

    assert result.data.results[0].entryId == "T1"


def test_task_search_tool_explicit_limit_bounds_and_flags_truncated(mocker):
    import server
    from models.schemas import TaskDetail, TaskStatus

    mocker.patch("tools.settings.load_settings", return_value={})
    tasks = [
        TaskDetail(
            entry_id=f"T{i}",
            subject="Renovar licencia",
            due_date=None,
            status=TaskStatus.IN_PROGRESS,
            is_complete=False,
            body="",
        )
        for i in range(10)
    ]
    fake_tasks = FakeTaskAdapter(tasks=tasks)
    app = server.create_server(task_adapter=fake_tasks)

    async def _call():
        async with Client(app) as client:
            return await client.call_tool("task_search", {"limit": 3})

    result = asyncio.run(_call())

    assert len(result.data.results) == 3
    assert result.data.resultsTruncated is True


def test_stdio_only_no_network_listener(mocker):
    """The server MUST run over stdio only — no TCP/HTTP listener, no auth.
    We assert `main()` drives FastMCP's own `.run()` with `transport="stdio"`
    (and nothing else, e.g. no host/port kwargs), rather than actually
    binding a socket in a unit test."""
    import server

    run_mock = mocker.patch.object(server.FastMCP, "run", autospec=True)

    server.main()

    run_mock.assert_called_once()
    _self, *args = run_mock.call_args.args
    kwargs = run_mock.call_args.kwargs
    assert (args and args[0] == "stdio") or kwargs.get("transport") == "stdio"
    assert "host" not in kwargs
    assert "port" not in kwargs


def test_force_utf8_stdio_reconfigures_streams_that_support_it(mocker):
    """Windows Python encodes stdout in the legacy console codepage by
    default, corrupting UTF-8 JSON-RPC (mojibake in accented event
    subjects). `_force_utf8_stdio()` must reconfigure stdin/stdout/stderr to
    UTF-8 when the stream supports `.reconfigure(encoding=...)`, and must
    not raise on streams that don't (e.g. redirected/piped streams in some
    test harnesses)."""
    import server

    fake_stdin = mocker.Mock()
    fake_stdout = mocker.Mock()
    fake_stderr = mocker.Mock()
    mocker.patch.object(server.sys, "stdin", fake_stdin)
    mocker.patch.object(server.sys, "stdout", fake_stdout)
    mocker.patch.object(server.sys, "stderr", fake_stderr)

    server._force_utf8_stdio()

    fake_stdin.reconfigure.assert_called_once_with(encoding="utf-8")
    fake_stdout.reconfigure.assert_called_once_with(encoding="utf-8")
    fake_stderr.reconfigure.assert_called_once_with(encoding="utf-8")


def test_force_utf8_stdio_tolerates_streams_without_reconfigure(mocker):
    """A stream that lacks `.reconfigure` (e.g. a plain io.BytesIO wrapper
    or some redirected-stream shims) must not crash the call."""
    import server

    class NoReconfigure:
        pass

    mocker.patch.object(server.sys, "stdout", NoReconfigure())

    server._force_utf8_stdio()  # must not raise


def test_main_forces_utf8_stdio_before_running(mocker):
    """`main()` must call `_force_utf8_stdio()` before starting the server,
    so the fix is wired into the real entrypoint, not just available as an
    unused helper."""
    import server

    force_utf8_mock = mocker.patch.object(server, "_force_utf8_stdio")
    run_mock = mocker.patch.object(server.FastMCP, "run", autospec=True)

    server.main()

    force_utf8_mock.assert_called_once()
    run_mock.assert_called_once()


def test_adapter_selection_deferred_when_win32com_unavailable(mocker):
    """Import + server construction must succeed even though win32com is
    genuinely unavailable on this host; only the actual tool *call* should
    fail, with a clear error — not an import-time or construction-time
    crash."""
    mocker.patch.dict(sys.modules)
    sys.modules.pop("win32com", None)
    sys.modules.pop("win32com.client", None)

    import server

    app = server.create_server()  # no adapter injected -> real lazy adapter

    async def _call():
        async with Client(app) as client:
            return await client.call_tool("calendar_search", {"subject": "test"})

    with pytest.raises(ToolError):
        asyncio.run(_call())


def test_task_adapter_selection_deferred_when_win32com_unavailable(mocker):
    """Mirrors test_adapter_selection_deferred_when_win32com_unavailable for
    the task adapter path: import + server construction must succeed even
    though win32com is genuinely unavailable; only the actual task_search
    call should fail, with a clear error — not an import-time or
    construction-time crash."""
    mocker.patch.dict(sys.modules)
    sys.modules.pop("win32com", None)
    sys.modules.pop("win32com.client", None)

    import server

    app = server.create_server()  # no task_adapter injected -> real lazy adapter

    async def _call():
        async with Client(app) as client:
            return await client.call_tool("task_search", {})

    with pytest.raises(ToolError):
        asyncio.run(_call())


def test_calendar_search_tool_returns_results_via_fake_adapter():
    import server

    # Relative to "now" (not hardcoded) so this stays inside the tool's
    # default 7-day lookback window regardless of when the suite runs.
    now = datetime.now(timezone.utc)
    detail = EventDetail(
        entry_id="ABC123",
        subject="Tareas (bloque)",
        start=now - timedelta(hours=1),
        end=now - timedelta(minutes=30),
        body="notas",
    )
    fake = FakeCalendarAdapter(events=[detail])
    app = server.create_server(adapter=fake)

    async def _call():
        async with Client(app) as client:
            return await client.call_tool("calendar_search", {"subject": "tareas"})

    result = asyncio.run(_call())

    assert result.data.results[0].entryId == "ABC123"


def test_calendar_search_tool_explicit_limit_bounds_and_flags_truncated(mocker):
    import server

    mocker.patch("tools.settings.load_settings", return_value={})
    now = datetime.now(timezone.utc)
    events = [
        EventDetail(
            entry_id=f"E{i}",
            subject="Tareas (bloque)",
            start=now - timedelta(hours=i + 1),
            end=now - timedelta(hours=i, minutes=30),
            body="",
        )
        for i in range(10)
    ]
    fake = FakeCalendarAdapter(events=events)
    app = server.create_server(adapter=fake)

    async def _call():
        async with Client(app) as client:
            return await client.call_tool("calendar_search", {"subject": "tareas", "limit": 3})

    result = asyncio.run(_call())

    assert len(result.data.results) == 3
    assert result.data.resultsTruncated is True


def test_calendar_search_no_filters_surfaces_as_tool_error():
    import server

    fake = FakeCalendarAdapter(events=[])
    app = server.create_server(adapter=fake)

    async def _call():
        async with Client(app) as client:
            return await client.call_tool("calendar_search", {})

    with pytest.raises(ToolError):
        asyncio.run(_call())


def test_calendar_get_notes_ambiguous_match_surfaces_as_tool_error():
    import server

    events = [
        EventDetail(
            entry_id="A1", subject="Tareas (bloque)",
            start=datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc),
            end=datetime(2026, 7, 27, 9, 30, tzinfo=timezone.utc), body="",
        ),
        EventDetail(
            entry_id="A2", subject="Tareas (otro)",
            start=datetime(2026, 7, 27, 11, 0, tzinfo=timezone.utc),
            end=datetime(2026, 7, 27, 11, 30, tzinfo=timezone.utc), body="",
        ),
    ]
    fake = FakeCalendarAdapter(events=events)
    app = server.create_server(adapter=fake)

    async def _call():
        async with Client(app) as client:
            return await client.call_tool(
                "calendar_get_notes", {"date": "2026-07-27", "subject": "Tareas"}
            )

    with pytest.raises(ToolError, match="ambiguous_match"):
        asyncio.run(_call())


def test_onenote_tools_registered_via_fake_onenote_adapter():
    """Phase 9: onenote_search/onenote_get_page/onenote_create_page/
    onenote_update_page must be registered alongside every other tool when
    a FakeOneNoteAdapter is injected via the new `onenote_adapter`
    create_server() parameter — mirrors
    test_file_search_tools_registered_via_fake_file_search_adapter's
    shape."""
    import server

    fake_onenote = FakeOneNoteAdapter(pages=[], hierarchy=[])
    app = server.create_server(onenote_adapter=fake_onenote)

    async def _list_names():
        async with Client(app) as client:
            tools = await client.list_tools()
            return {tool.name for tool in tools}

    names = asyncio.run(_list_names())

    assert names == _ALL_TOOL_NAMES


def test_onenote_search_tool_returns_results_via_fake_onenote_adapter():
    """End-to-end onenote_search call via FastMCP's in-process Client,
    mirroring test_mail_search_tool_returns_results_via_fake_mail_adapter's
    shape. `onenote_search` returns a bare `list[PageSummary]` (no
    `resultsTruncated` envelope — design.md's Batch-2 deviation note #4),
    unlike mail_search/calendar_search/task_search."""
    import server

    page = PageDetail(
        page_id="P-1",
        title="Reunión de proyecto",
        notebook_name="Informa - Proyectos",
        section_name="2026",
        body_text="Notas de la reunión",
    )
    fake_onenote = FakeOneNoteAdapter(pages=[page])
    app = server.create_server(onenote_adapter=fake_onenote)

    async def _call():
        async with Client(app) as client:
            return await client.call_tool("onenote_search", {"query": "reunión"})

    result = asyncio.run(_call())

    assert result.data[0].pageId == "P-1"


def test_onenote_search_tool_empty_query_surfaces_invalid_request_tool_error():
    """`onenote_search` with an empty `query` must surface the tool layer's
    plain `ValueError` as an `[invalid_request]` ToolError, before any
    adapter call — mirrors test_file_search_tool_no_filters_surfaces_
    invalid_request_tool_error's shape."""
    import server

    fake_onenote = FakeOneNoteAdapter(pages=[])
    app = server.create_server(onenote_adapter=fake_onenote)

    async def _call():
        async with Client(app) as client:
            return await client.call_tool("onenote_search", {"query": ""})

    with pytest.raises(ToolError, match="invalid_request"):
        asyncio.run(_call())


def test_onenote_get_page_tool_returns_detail_via_fake_onenote_adapter():
    """End-to-end onenote_get_page call via FastMCP's in-process Client."""
    import server

    page = PageDetail(
        page_id="P-2",
        title="Plan Q3",
        notebook_name="Informa - Proyectos",
        section_name="2026",
        body_text="Objetivos del trimestre",
    )
    fake_onenote = FakeOneNoteAdapter(pages=[page])
    app = server.create_server(onenote_adapter=fake_onenote)

    async def _call():
        async with Client(app) as client:
            return await client.call_tool("onenote_get_page", {"pageId": "P-2"})

    result = asyncio.run(_call())

    assert result.data.bodyText == "Objetivos del trimestre"


def test_onenote_get_page_tool_unknown_id_surfaces_page_not_found_error():
    """An unresolved `pageId` must surface `OneNotePageNotFoundError` as an
    `[onenote_page_not_found]` ToolError via the existing `_map_error`
    `CalendarToolError` base-class catch — no explicit onenote branch
    needed in `_map_error`, mirroring
    test_mail_search_tool_folder_path_unresolved_returns_mail_folder_
    not_found_error's shape."""
    import server

    fake_onenote = FakeOneNoteAdapter(pages=[])
    app = server.create_server(onenote_adapter=fake_onenote)

    async def _call():
        async with Client(app) as client:
            return await client.call_tool("onenote_get_page", {"pageId": "MISSING"})

    with pytest.raises(ToolError, match="onenote_page_not_found"):
        asyncio.run(_call())


def test_onenote_create_page_tool_returns_new_page_via_fake_onenote_adapter():
    """End-to-end onenote_create_page call, writing to the default
    writable test notebook seeded in the fixture hierarchy."""
    import server

    hierarchy = [
        NotebookNode(
            notebook_id="NB-1",
            name="z - Test Notebook",
            sections=[SectionNode(section_id="SEC-1", name="General")],
        )
    ]
    fake_onenote = FakeOneNoteAdapter(pages=[], hierarchy=hierarchy)
    app = server.create_server(onenote_adapter=fake_onenote)

    async def _call():
        async with Client(app) as client:
            return await client.call_tool(
                "onenote_create_page",
                {"sectionId": "SEC-1", "title": "Nueva página", "bodyText": "Contenido"},
            )

    result = asyncio.run(_call())

    assert result.data.title == "Nueva página"
    assert result.data.pageId


def test_onenote_create_page_tool_live_notebook_refused_surfaces_tool_error():
    """A `sectionId` resolving to a notebook NOT in the writable allowlist
    must be refused with an `[onenote_notebook_not_allowed]` ToolError,
    before any write is attempted — the onenote-write-page spec's
    "Writable Notebook Allowlist" requirement, exercised end-to-end
    through server.py."""
    import server

    hierarchy = [
        NotebookNode(
            notebook_id="NB-2",
            name="Informa - Proyectos",
            sections=[SectionNode(section_id="SEC-2", name="2026")],
        )
    ]
    fake_onenote = FakeOneNoteAdapter(pages=[], hierarchy=hierarchy)
    app = server.create_server(onenote_adapter=fake_onenote)

    async def _call():
        async with Client(app) as client:
            return await client.call_tool(
                "onenote_create_page",
                {"sectionId": "SEC-2", "title": "x", "bodyText": "x"},
            )

    with pytest.raises(ToolError, match="onenote_notebook_not_allowed"):
        asyncio.run(_call())


def test_onenote_update_page_tool_matching_date_succeeds():
    """End-to-end onenote_update_page call with a matching
    `dateExpectedLastModified` must succeed and return the new body."""
    import server

    now = datetime.now(timezone.utc)
    page = PageDetail(
        page_id="P-3",
        title="Notas",
        notebook_name="z - Test Notebook",
        section_name="General",
        body_text="Viejo contenido",
        last_modified=now,
    )
    fake_onenote = FakeOneNoteAdapter(pages=[page])
    app = server.create_server(onenote_adapter=fake_onenote)

    async def _call():
        async with Client(app) as client:
            return await client.call_tool(
                "onenote_update_page",
                {
                    "pageId": "P-3",
                    "bodyText": "Nuevo contenido",
                    "dateExpectedLastModified": now.isoformat(),
                },
            )

    result = asyncio.run(_call())

    assert result.data.bodyText == "Nuevo contenido"


def test_onenote_update_page_tool_stale_date_surfaces_conflict_error():
    """A stale `dateExpectedLastModified` must surface
    `OneNotePageConflictError` as an `[onenote_page_conflict]` ToolError,
    and the fake adapter's seeded page must remain unchanged."""
    import server

    now = datetime.now(timezone.utc)
    page = PageDetail(
        page_id="P-4",
        title="Notas",
        notebook_name="z - Test Notebook",
        section_name="General",
        body_text="Contenido original",
        last_modified=now,
    )
    fake_onenote = FakeOneNoteAdapter(pages=[page])
    app = server.create_server(onenote_adapter=fake_onenote)

    stale = now - timedelta(hours=1)

    async def _call():
        async with Client(app) as client:
            return await client.call_tool(
                "onenote_update_page",
                {
                    "pageId": "P-4",
                    "bodyText": "Intento de sobrescritura",
                    "dateExpectedLastModified": stale.isoformat(),
                },
            )

    with pytest.raises(ToolError, match="onenote_page_conflict"):
        asyncio.run(_call())


def _list_registered_tool_names(app):
    async def _list_names():
        async with Client(app) as client:
            tools = await client.list_tools()
            return {tool.name for tool in tools}

    return asyncio.run(_list_names())


def test_create_server_installed_none_registers_all_15_tools():
    """Back-compat: `installed=None` (the default, and the value
    `settings.installed_tools()` returns when `config/installed-
    tools.yaml` is absent) must register every catalog tool, byte-
    identical to pre-selective-deploy behavior."""
    import server

    app = server.create_server(
        adapter=FakeCalendarAdapter(events=[]),
        task_adapter=FakeTaskAdapter(tasks=[]),
        mail_adapter=FakeMailAdapter(inbox=[]),
        file_search_adapter=FakeFileSearchAdapter(files=[]),
        onenote_adapter=FakeOneNoteAdapter(pages=[]),
        installed=None,
    )

    assert _list_registered_tool_names(app) == _ALL_TOOL_NAMES


def test_create_server_narrowed_installed_registers_only_those_tools():
    """A 2-tool `installed` set must register exactly those two tools —
    the mcp-server-bootstrap delta's "Only enabled tools are discoverable
    when the config file exists" scenario."""
    import server

    app = server.create_server(
        adapter=FakeCalendarAdapter(events=[]),
        task_adapter=FakeTaskAdapter(tasks=[]),
        mail_adapter=FakeMailAdapter(inbox=[]),
        file_search_adapter=FakeFileSearchAdapter(files=[]),
        onenote_adapter=FakeOneNoteAdapter(pages=[]),
        installed={"calendar_search", "mail_search"},
    )

    assert _list_registered_tool_names(app) == {"calendar_search", "mail_search"}


def test_create_server_empty_installed_registers_zero_tools():
    """Triangulation: an empty (but non-None) `installed` set must
    register nothing at all — distinct from `installed=None`'s
    "everything" back-compat sentinel."""
    import server

    app = server.create_server(
        adapter=FakeCalendarAdapter(events=[]),
        task_adapter=FakeTaskAdapter(tasks=[]),
        mail_adapter=FakeMailAdapter(inbox=[]),
        file_search_adapter=FakeFileSearchAdapter(files=[]),
        onenote_adapter=FakeOneNoteAdapter(pages=[]),
        installed=set(),
    )

    assert _list_registered_tool_names(app) == set()


def test_import_succeeds_regardless_of_installed_tools_value(mocker):
    """mcp-server-bootstrap delta's "Import Safety Independent of
    Registration Gating" requirement: importing `server` must succeed no
    matter what `settings.installed_tools()` would return — a narrowed
    set here — since registration gating must never be achieved via
    conditional imports. Reloading (rather than a fresh `import`) proves
    the module body itself tolerates re-execution with a mocked
    `installed_tools()` in place, not just a cached first import."""
    mocker.patch("tools.settings.installed_tools", return_value={"calendar_search"})

    import server

    importlib.reload(server)

    # The reload itself succeeding (no exception) is the assertion; also
    # confirm every tool module is still statically imported regardless
    # (task 4.4: shipped-but-disabled preserved, no conditional imports).
    assert "tools.task_adapter" in sys.modules
    assert "tools.mail_adapter" in sys.modules
    assert "tools.file_search_adapter" in sys.modules
    assert "tools.onenote_adapter" in sys.modules


def test_import_succeeds_when_installed_tools_config_file_absent(mocker):
    """Mirrors the delta spec's other import-safety scenario: the file
    absent (`installed_tools()` returning `None`) must not break import
    either — exactly as it did before this change."""
    mocker.patch("tools.settings.installed_tools", return_value=None)

    import server

    importlib.reload(server)

    assert "tools.onenote_adapter" in sys.modules


# ---------------------------------------------------------------------------
# hard-tool-exclusion Phase 2: per-family `find_spec` import guards +
# `_tool_enabled()`'s shipped/installed ceiling (design.md Decision 1/2,
# mcp-server-bootstrap delta's "Import Safety Under Physical Family
# Absence" and "Tool Registration" requirements).
# ---------------------------------------------------------------------------


def test_import_succeeds_with_one_family_absent_and_registers_zero_of_its_tools():
    """Simulate the `onenote` family's modules being physically absent (a
    hard-excluded share build) via a monkeypatched `importlib.util.find_spec`
    -- server.py must still import cleanly and register zero onenote tools,
    while every other family's tools stay registered normally. Uses a plain
    `unittest.mock.patch` context manager (not the `mocker` fixture) so the
    patch is fully torn down by the time the `finally` reload runs -- the
    `mocker` fixture only undoes its patches at test teardown, which would
    happen AFTER a `finally`-block reload and leave server.py's module-level
    `_ONENOTE_PRESENT`/etc. flags permanently stuck in the faked-absent
    state for every later test in this file."""
    import server

    real_find_spec = importlib.util.find_spec

    def _fake_find_spec(name, *args, **kwargs):
        if name in ("tools.onenote", "tools.onenote_adapter"):
            return None
        return real_find_spec(name, *args, **kwargs)

    try:
        with mock.patch("importlib.util.find_spec", side_effect=_fake_find_spec):
            importlib.reload(server)

            app = server.create_server(
                adapter=FakeCalendarAdapter(events=[]),
                task_adapter=FakeTaskAdapter(tasks=[]),
                mail_adapter=FakeMailAdapter(inbox=[]),
                file_search_adapter=FakeFileSearchAdapter(files=[]),
            )
            names = _list_registered_tool_names(app)
    finally:
        importlib.reload(server)

    assert names == _ALL_TOOL_NAMES - {
        "onenote_search",
        "onenote_get_page",
        "onenote_list_sections",
        "onenote_list_pages",
        "onenote_create_page",
        "onenote_update_page",
    }


def test_import_succeeds_with_mail_absent_and_other_families_still_register():
    """Triangulates the import-safety guard with a different family (`mail`)
    absent instead of `onenote` -- mcp-server-bootstrap delta's "An absent
    family does not break a present family's registration" scenario:
    calendar/task/file/onenote must all still register normally. See the
    previous test's docstring for why a plain `unittest.mock.patch` context
    manager is used here instead of the `mocker` fixture."""
    import server

    real_find_spec = importlib.util.find_spec

    def _fake_find_spec(name, *args, **kwargs):
        if name in ("tools.mail", "tools.mail_adapter"):
            return None
        return real_find_spec(name, *args, **kwargs)

    try:
        with mock.patch("importlib.util.find_spec", side_effect=_fake_find_spec):
            importlib.reload(server)

            app = server.create_server(
                adapter=FakeCalendarAdapter(events=[]),
                task_adapter=FakeTaskAdapter(tasks=[]),
                file_search_adapter=FakeFileSearchAdapter(files=[]),
                onenote_adapter=FakeOneNoteAdapter(pages=[]),
            )
            names = _list_registered_tool_names(app)
    finally:
        importlib.reload(server)

    assert names == _ALL_TOOL_NAMES - {"mail_search", "mail_get_message"}


def test_create_server_shipped_none_falls_back_to_installed_only_today_behavior():
    """`shipped=None` (legacy/full-repo runs, no manifest) must not narrow
    registration beyond `installed` -- exactly today's pre-hard-tool-
    exclusion behavior, unweakened by the new ceiling."""
    import server

    app = server.create_server(
        adapter=FakeCalendarAdapter(events=[]),
        task_adapter=FakeTaskAdapter(tasks=[]),
        mail_adapter=FakeMailAdapter(inbox=[]),
        file_search_adapter=FakeFileSearchAdapter(files=[]),
        onenote_adapter=FakeOneNoteAdapter(pages=[]),
        shipped=None,
        installed={"calendar_search", "mail_search"},
    )

    assert _list_registered_tool_names(app) == {"calendar_search", "mail_search"}


def test_create_server_shipped_ceiling_blocks_unshipped_sibling_even_if_installed():
    """A tool present in `installed` but absent from a non-`None` `shipped`
    set must stay unregistered -- the hard ceiling, mcp-server-bootstrap
    delta's "A hand-edited config cannot resurrect a hard-excluded tool"
    scenario."""
    import server

    app = server.create_server(
        adapter=FakeCalendarAdapter(events=[]),
        task_adapter=FakeTaskAdapter(tasks=[]),
        mail_adapter=FakeMailAdapter(inbox=[]),
        file_search_adapter=FakeFileSearchAdapter(files=[]),
        onenote_adapter=FakeOneNoteAdapter(pages=[]),
        shipped={"onenote_search"},
        installed={"onenote_search", "onenote_update_page"},
    )

    assert _list_registered_tool_names(app) == {"onenote_search"}


def test_create_server_shipped_present_installed_absent_registers_every_shipped_tool():
    """`shipped` present, `installed` absent (`None`) -- mcp-server-bootstrap
    delta's "every shipped tool" precedence row (back-compat: "absent
    config = install all", scoped to what shipped)."""
    import server

    app = server.create_server(
        adapter=FakeCalendarAdapter(events=[]),
        task_adapter=FakeTaskAdapter(tasks=[]),
        mail_adapter=FakeMailAdapter(inbox=[]),
        file_search_adapter=FakeFileSearchAdapter(files=[]),
        onenote_adapter=FakeOneNoteAdapter(pages=[]),
        shipped={"calendar_search", "mail_search"},
        installed=None,
    )

    assert _list_registered_tool_names(app) == {"calendar_search", "mail_search"}


def test_create_server_shipped_and_installed_both_present_registers_intersection():
    """Both `shipped` and `installed` present -- the intersection row of the
    precedence table."""
    import server

    app = server.create_server(
        adapter=FakeCalendarAdapter(events=[]),
        task_adapter=FakeTaskAdapter(tasks=[]),
        mail_adapter=FakeMailAdapter(inbox=[]),
        file_search_adapter=FakeFileSearchAdapter(files=[]),
        onenote_adapter=FakeOneNoteAdapter(pages=[]),
        shipped={"calendar_search", "mail_search", "task_search"},
        installed={"calendar_search", "task_search"},
    )

    assert _list_registered_tool_names(app) == {"calendar_search", "task_search"}


def test_registration_ceiling_end_to_end_via_real_deployed_layout(tmp_path, mocker):
    """Task 4 (Phase 4) integration scenario: a hand-edited
    `config/installed-tools.yaml` naming a tool absent from a real, on-disk
    `tools/shipped-tools.json` must still be refused -- proven end-to-end
    through the REAL `tools.settings.shipped_tools()`/`installed_tools()`
    file-reading path (both module-level path constants monkeypatched to a
    fake deployed layout under `tmp_path`), not by injecting `shipped=`/
    `installed=` dicts directly as the precedence-table tests above do.
    This closes the one gap those unit tests leave open: they exercise
    `create_server()`'s ceiling logic, but never the wiring from real
    manifest/config files on disk through to registration -- the exact
    "hand-edit can't resurrect a hard-excluded tool" scenario a recipient
    of a share package would hit, minus only the actual Windows install
    step (Phase 5, deferred/manual)."""
    manifest_path = tmp_path / "shipped-tools.json"
    manifest_path.write_text(
        json.dumps(
            {
                "build_mode": "share",
                "families": [
                    {
                        "name": "onenote",
                        "tools": [
                            {
                                "name": "onenote_search",
                                "maturity": "beta",
                                "default_enabled": True,
                            },
                        ],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    installed_path = tmp_path / "installed-tools.yaml"
    installed_path.write_text(
        yaml.safe_dump(
            {"tools": ["onenote_search", "onenote_update_page"]},
        ),
        encoding="utf-8",
    )
    mocker.patch("tools.settings._SHIPPED_TOOLS_PATH", manifest_path)
    mocker.patch("tools.settings._INSTALLED_TOOLS_PATH", installed_path)

    from tools import settings

    import server

    app = server.create_server(
        adapter=FakeCalendarAdapter(events=[]),
        task_adapter=FakeTaskAdapter(tasks=[]),
        mail_adapter=FakeMailAdapter(inbox=[]),
        file_search_adapter=FakeFileSearchAdapter(files=[]),
        onenote_adapter=FakeOneNoteAdapter(pages=[]),
        shipped=settings.shipped_tools(),
        installed=settings.installed_tools(),
    )

    # onenote_update_page was hand-edited into installed-tools.yaml but was
    # never shipped -- the hard ceiling must refuse it. onenote_search is
    # both shipped and installed, so it registers normally.
    assert _list_registered_tool_names(app) == {"onenote_search"}


def test_main_passes_shipped_tools_to_create_server(mocker):
    """`main()` must resolve `shipped` from `tools.settings.shipped_tools()`
    and forward it to `create_server()`, mirroring how it already forwards
    `installed` from `installed_tools()`."""
    import server

    mocker.patch("tools.settings.installed_tools", return_value=None)
    mocker.patch("tools.settings.shipped_tools", return_value={"calendar_search"})
    create_server_mock = mocker.patch.object(
        server, "create_server", wraps=server.create_server
    )
    mocker.patch.object(server.FastMCP, "run", autospec=True)

    server.main()

    create_server_mock.assert_called_once()
    _, kwargs = create_server_mock.call_args
    assert kwargs.get("shipped") == {"calendar_search"}


def test_onenote_adapter_selection_deferred_when_bridge_unavailable():
    """Import + server construction must succeed with no injected
    `onenote_adapter` (the real, lazily-resolved `OneNoteAdapter`); only
    the actual onenote_search call should fail, with a clear
    `[onenote_unavailable]`-prefixed error — not an import-time or
    construction-time crash. Unlike the Outlook/file-search adapters,
    `OneNoteAdapter` never touches win32com at all — it fails here because
    this WSL2 host genuinely has no `powershell.exe` for
    `PsBridgeTransport` to spawn, which is exactly the real-world
    "bridge unavailable" condition this test stands in for."""
    import server

    app = server.create_server()  # no onenote_adapter injected -> real lazy adapter

    async def _call():
        async with Client(app) as client:
            return await client.call_tool("onenote_search", {"query": "x"})

    with pytest.raises(ToolError, match="onenote_unavailable"):
        asyncio.run(_call())


# ---------------------------------------------------------------------------
# hard-tool-exclusion Batch 4 (verify-report.md WARNING 1): permanent
# regression test proving a genuine bug inside a PRESENT family module
# still propagates through server.py's `find_spec`-presence guard, rather
# than being swallowed as "family absent". The monkeypatched-`find_spec`
# tests above (`test_import_succeeds_with_one_family_absent_and_registers_
# zero_of_its_tools` etc.) only prove the guard's *absent* branch; they
# never exercise what happens when the guarded `from tools.X import ...`
# statement itself raises, and they run in-process via `importlib.reload`,
# which cannot exercise server.py's module-level guard code genuinely
# fresh the way a brand-new subprocess does. These two tests run a real
# `python -c "import server"` subprocess against a hermetic tmp_path copy
# of the real tools/, models/, and server.py -- no repo file is ever
# touched.
# ---------------------------------------------------------------------------


def _hermetic_repo_copy(tmp_path: Path) -> Path:
    """Copy just enough of the real repo (`tools/`, `models/`, `server.py`)
    into `tmp_path` for a fresh `python -c "import server"` subprocess run
    with `cwd=tmp_path` to exercise server.py's real, unmocked module-level
    `find_spec` guards. `__pycache__` is skipped (not needed, keeps the
    copy fast); nothing under the real repo is ever written to."""
    repo_root = Path(__file__).resolve().parent.parent
    for name in ("tools", "models"):
        shutil.copytree(
            repo_root / name,
            tmp_path / name,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
    shutil.copy2(repo_root / "server.py", tmp_path / "server.py")
    return tmp_path


def _run_import_server(cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", "import server"],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_present_but_internally_broken_family_module_still_raises_not_swallowed(
    tmp_path,
):
    """The single most safety-critical property of design.md Decision 1:
    `importlib.util.find_spec` only asks "is this module discoverable" --
    it never executes the module body -- so a genuine bug that only
    manifests when a PRESENT family module actually runs must still
    propagate uncaught through `import server`, exactly as it did before
    this change (never masked as "family absent").

    Deliberately uses a bug that raises `ModuleNotFoundError` (an
    `ImportError` subclass) from INSIDE the family module -- a stray/
    typo'd internal import referencing a module that genuinely doesn't
    exist -- rather than a plain `SyntaxError`. `SyntaxError` is never an
    `ImportError` subclass, so it propagates identically whether the guard
    is written correctly (`find_spec`-gated) or replaced by the exact
    anti-pattern this test exists to catch (`try: from tools.X import ...
    except ImportError: ...` -- "for safety"); it would NOT be RED against
    that regression. Empirically verified while writing this test (a
    one-off local experiment, not shipped): with `tools/calendar.py`'s
    guard temporarily rewritten to that blind `try/except ImportError`
    shape, this exact bug was silently swallowed -- `import server` exited
    0 with zero calendar tools registered, mimicking "family absent" --
    then the guard was restored unchanged. A `SyntaxError`-based version of
    this test would have passed (exit nonzero) under BOTH the correct
    guard and that anti-pattern, so it would not have caught the
    regression; this ModuleNotFoundError-shaped bug does."""
    _hermetic_repo_copy(tmp_path)
    (tmp_path / "tools" / "calendar.py").write_text(
        "import tools.this_module_does_not_exist_at_all_xyz\n",
        encoding="utf-8",
    )

    result = _run_import_server(tmp_path)

    assert result.returncode != 0, (
        "a present-but-internally-broken family module must crash "
        "`import server`, not start cleanly with that family silently "
        f"dropped -- stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "ModuleNotFoundError" in result.stderr
    assert "this_module_does_not_exist_at_all_xyz" in result.stderr


def test_genuinely_absent_family_module_still_imports_cleanly(tmp_path):
    """Inverse control for the test above: when a family's modules are
    genuinely, physically absent (the real hard-tool-exclusion scenario --
    a `--share` build that omitted them), `import server` must still
    succeed cleanly. The tests above already prove this in-process via a
    monkeypatched `find_spec`; this proves the same thing end-to-end
    through the real, unmocked import machinery in a fresh subprocess."""
    _hermetic_repo_copy(tmp_path)
    (tmp_path / "tools" / "calendar.py").unlink()
    (tmp_path / "tools" / "outlook_adapter.py").unlink()

    result = _run_import_server(tmp_path)

    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert result.stderr == ""


def test_server_info_tool_identifies_the_deployment():
    """add-server-info change (cowork mailbox request 2026-08-28): the
    deployment identifies itself — install root, enabled tool names, and
    (on a source checkout, which this test runs on) null stamp fields
    with a note naming build-info.json."""
    import server

    app = server.create_server(adapter=FakeCalendarAdapter(events=[]))

    async def _call():
        async with Client(app) as client:
            return await client.call_tool("server_info", {})

    result = asyncio.run(_call())

    assert Path(result.data.installRoot, "server.py").exists()
    assert set(result.data.enabledTools) == _ALL_TOOL_NAMES
    assert result.data.enabledTools == sorted(result.data.enabledTools)
    assert result.data.package is None
    assert "build-info.json" in result.data.note


def test_onenote_list_pages_tool_returns_section_pages_via_fake_adapter():
    """End-to-end onenote_list_pages call via FastMCP's in-process Client
    (add-onenote-list-pages): enumeration must come from the hierarchy
    route, independent of the search index, with the owning notebook name
    resolved onto every row."""
    import server

    hierarchy = [
        NotebookNode(
            notebook_id="{NB-1}{1}{B0}",
            name="z - Test Notebook",
            sections=[SectionNode(section_id="{SEC-1}{1}{B0}", name="New Section 1")],
        )
    ]
    page = PageDetail(
        page_id="PAGE-COS",
        title="COS - test table with formatting",
        body_text="Title 1",
        notebook_name="",
        section_name="New Section 1",
        section_id="{SEC-1}{1}{B0}",
    )
    fake_onenote = FakeOneNoteAdapter(pages=[page], hierarchy=hierarchy)
    app = server.create_server(onenote_adapter=fake_onenote)

    async def _call():
        async with Client(app) as client:
            return await client.call_tool(
                "onenote_list_pages", {"sectionId": "{SEC-1}{1}{B0}"}
            )

    result = asyncio.run(_call())
    rows = result.structured_content["result"]

    assert [row["pageId"] for row in rows] == ["PAGE-COS"]
    assert rows[0]["notebookName"] == "z - Test Notebook"
    assert rows[0]["sectionName"] == "New Section 1"
