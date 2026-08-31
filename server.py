"""FastMCP server exposing the Outlook calendar, Tasks/To Do, Mail, file
search, and OneNote tools over stdio.

Registers `calendar_search`, `calendar_get_event`, `calendar_get_notes`
(mcp-server-bootstrap spec's "Tool Registration" requirement),
`task_search`, `task_get_task` (outlook-tasks-adapter/task-search/
task-get-detail specs), `mail_search`, `mail_get_message`
(outlook-mail-adapter/mail-search/mail-get-detail specs), `file_search`,
`file_get_info` (file-search/file-get-info/windows-search-adapter specs),
and `onenote_search`, `onenote_get_page`, `onenote_list_sections`,
`onenote_list_pages`, `onenote_create_page`, `onenote_update_page`
(onenote-search/onenote-get-page/onenote-write-page/
onenote-com-adapter specs, add-onenote-adapter change), and serves them
over stdio only — no network listener, no authentication ("Transport and
Access Scope" requirement).

Adapter selection is deferred to first tool invocation: importing this
module (e.g. by `python3.12 -m pytest -q` on this WSL2 host) MUST NOT
import `win32com` or fail ("Import-Time Safety on Non-Windows Hosts"
requirement) — `OneNoteAdapter` never imports `win32com` at all; it talks
to OneNote exclusively through the shared `PsBridgeTransport`'s
`powershell.exe`/COM bridge, same seam as `file_search`'s PowerShell
fallback. `create_server()` accepts injectable `adapter`/`task_adapter`/
`mail_adapter`/`file_search_adapter`/`onenote_adapter` parameters for
tests (a `FakeCalendarAdapter`/`FakeTaskAdapter`/`FakeMailAdapter`/
`FakeFileSearchAdapter`/`FakeOneNoteAdapter`); production use (the
`main()` entrypoint) leaves all five `None` so the real
`OutlookCalendarAdapter`/`OutlookTaskAdapter`/`OutlookMailAdapter`/
`WindowsSearchAdapter`/`OneNoteAdapter` are constructed lazily, on the
first tool call, per outlook-com-adapter/outlook-tasks-adapter/
outlook-mail-adapter/windows-search-adapter/onenote-com-adapter specs'
"Adapter Selection at Runtime" requirement.
"""
import importlib.util
import sys
from datetime import date as date_
from datetime import datetime
from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from models.schemas import (
    CalendarSearchResult,
    CreatePageRequest,
    DeploymentInfo,
    EventDetail,
    FileDetail,
    FileSearchRequest,
    FileSearchResponse,
    GetEventRequest,
    GetFileInfoRequest,
    GetMessageRequest,
    GetNotesRequest,
    GetPageRequest,
    GetTaskRequest,
    ListPagesRequest,
    MailFolder,
    MailSearchRequest,
    MailSearchResult,
    MessageDetail,
    OneNoteSearchRequest,
    PageDetail,
    PageSummary,
    SearchRequest,
    SectionInfo,
    TaskDetail,
    TaskSearchRequest,
    TaskSearchResult,
    TaskStatus,
    UpdatePageRequest,
)
from tools import settings
from tools.errors import CalendarToolError

# hard-tool-exclusion (design.md Decision 1): each family's tool-function +
# Port-type imports are guarded by an `importlib.util.find_spec` presence
# check, never imported unconditionally — a share build that physically
# omits a whole family's module files (its zero-selected `--share` tools)
# must still let `server.py` import cleanly; only that family's tool
# callables/Port type fall back to `None`/`Any` below, never an
# ImportError. `find_spec` only asks "is this module discoverable" — it
# never executes the module — so a genuine bug inside a PRESENT module
# (SyntaxError, NameError, etc.) still propagates normally, exactly as
# before this change. Always called as `importlib.util.find_spec(...)`
# (never `from importlib.util import find_spec`) so tests can monkeypatch
# it via `mocker.patch("importlib.util.find_spec", ...)`.
_CALENDAR_PRESENT = all(
    importlib.util.find_spec(m) is not None
    for m in ("tools.calendar", "tools.outlook_adapter")
)
if _CALENDAR_PRESENT:
    from tools.calendar import calendar_get_event, calendar_get_notes, calendar_search
    from tools.outlook_adapter import CalendarPort
else:
    calendar_get_event = calendar_get_notes = calendar_search = None
    CalendarPort = Any  # type: ignore[assignment,misc]

_TASK_PRESENT = all(
    importlib.util.find_spec(m) is not None for m in ("tools.tasks", "tools.task_adapter")
)
if _TASK_PRESENT:
    from tools.task_adapter import TaskPort
    from tools.tasks import task_get_task, task_search
else:
    task_get_task = task_search = None
    TaskPort = Any  # type: ignore[assignment,misc]

_MAIL_PRESENT = all(
    importlib.util.find_spec(m) is not None for m in ("tools.mail", "tools.mail_adapter")
)
if _MAIL_PRESENT:
    from tools.mail import mail_get_message, mail_search
    from tools.mail_adapter import MailPort
else:
    mail_get_message = mail_search = None
    MailPort = Any  # type: ignore[assignment,misc]

_FILE_PRESENT = all(
    importlib.util.find_spec(m) is not None
    for m in ("tools.file_search", "tools.file_search_adapter")
)
if _FILE_PRESENT:
    from tools.file_search import file_get_info, file_search
    from tools.file_search_adapter import FileSearchPort
else:
    file_get_info = file_search = None
    FileSearchPort = Any  # type: ignore[assignment,misc]

_ONENOTE_PRESENT = all(
    importlib.util.find_spec(m) is not None for m in ("tools.onenote", "tools.onenote_adapter")
)
if _ONENOTE_PRESENT:
    from tools.onenote import (
        onenote_create_page,
        onenote_get_page,
        onenote_list_pages,
        onenote_list_sections,
        onenote_search,
        onenote_update_page,
    )
    from tools.onenote_adapter import OneNotePort
else:
    onenote_create_page = onenote_get_page = onenote_search = onenote_update_page = None
    onenote_list_pages = onenote_list_sections = None
    OneNotePort = Any  # type: ignore[assignment,misc]

_SERVER_INFO_PRESENT = importlib.util.find_spec("tools.deployment_info") is not None
if _SERVER_INFO_PRESENT:
    from tools.deployment_info import deployment_info
else:
    deployment_info = None

# Maps each catalog tool name to its family's presence flag above — the
# runtime counterpart to `tools.catalog.py::families()`'s grouping, used by
# `_tool_enabled()` below so an absent family's tools are never registered
# regardless of `shipped`/`installed` (mcp-server-bootstrap delta's "Import
# Safety Under Physical Family Absence" requirement: zero tools from an
# absent family register, but this must never prevent any other present
# family's tools from registering).
_FAMILY_PRESENT_BY_TOOL = {
    "calendar_search": _CALENDAR_PRESENT,
    "calendar_get_event": _CALENDAR_PRESENT,
    "calendar_get_notes": _CALENDAR_PRESENT,
    "task_search": _TASK_PRESENT,
    "task_get_task": _TASK_PRESENT,
    "mail_search": _MAIL_PRESENT,
    "mail_get_message": _MAIL_PRESENT,
    "file_search": _FILE_PRESENT,
    "file_get_info": _FILE_PRESENT,
    "onenote_search": _ONENOTE_PRESENT,
    "onenote_get_page": _ONENOTE_PRESENT,
    "onenote_list_sections": _ONENOTE_PRESENT,
    "onenote_list_pages": _ONENOTE_PRESENT,
    "onenote_create_page": _ONENOTE_PRESENT,
    "onenote_update_page": _ONENOTE_PRESENT,
    "server_info": _SERVER_INFO_PRESENT,
}

_lazy_real_adapter: CalendarPort | None = None
_lazy_real_task_adapter: TaskPort | None = None
_lazy_real_mail_adapter: MailPort | None = None
_lazy_real_file_search_adapter: FileSearchPort | None = None
_lazy_real_onenote_adapter: OneNotePort | None = None


def _resolve_real_adapter() -> CalendarPort:
    """Build (and cache) the real win32com-backed adapter on first use —
    never at import time. Importing `tools.outlook_adapter` itself is safe
    on Linux (it defers its own `import win32com.client` further, inside
    the adapter's methods); this function just controls *when* the adapter
    object is constructed."""
    global _lazy_real_adapter
    if _lazy_real_adapter is None:
        from tools.outlook_adapter import OutlookCalendarAdapter

        _lazy_real_adapter = OutlookCalendarAdapter()
    return _lazy_real_adapter


def _resolve_real_task_adapter() -> TaskPort:
    """Build (and cache) the real win32com-backed task adapter on first
    use — never at import time. Mirrors `_resolve_real_adapter()`; importing
    `tools.task_adapter` itself is safe on Linux (its own
    `import win32com.client` is deferred further, inside
    `OutlookTaskAdapter`'s own methods)."""
    global _lazy_real_task_adapter
    if _lazy_real_task_adapter is None:
        from tools.task_adapter import OutlookTaskAdapter

        _lazy_real_task_adapter = OutlookTaskAdapter()
    return _lazy_real_task_adapter


def _resolve_real_mail_adapter() -> MailPort:
    """Build (and cache) the real win32com-backed mail adapter on first
    use — never at import time. Mirrors `_resolve_real_adapter()`/
    `_resolve_real_task_adapter()`; importing `tools.mail_adapter` itself is
    safe on Linux (its own `import win32com.client` is deferred further,
    inside `OutlookMailAdapter`'s own methods)."""
    global _lazy_real_mail_adapter
    if _lazy_real_mail_adapter is None:
        from tools.mail_adapter import OutlookMailAdapter

        _lazy_real_mail_adapter = OutlookMailAdapter()
    return _lazy_real_mail_adapter


def _resolve_real_file_search_adapter() -> FileSearchPort:
    """Build (and cache) the real file-search adapter on first use — never
    at import time. Mirrors `_resolve_real_mail_adapter()`; importing
    `tools.file_search_adapter` itself is safe on Linux (its own `import
    win32com.client`/`pythoncom`/`subprocess` invocation is deferred
    further, inside `WindowsSearchAdapter._dispatch_connection()`/
    `PowerShellSearchBridge._invoke()`).

    Constructs `FallbackSearchAdapter` (file-search-resilience change,
    Phase 6) rather than a bare `WindowsSearchAdapter` — its zero-arg
    default constructor wires the real `WindowsSearchAdapter` (ADO,
    primary) + `PowerShellSearchBridge` (fallback) automatically, per the
    windows-search-adapter spec's "Fallback Transport Ordering"
    requirement."""
    global _lazy_real_file_search_adapter
    if _lazy_real_file_search_adapter is None:
        from tools.file_search_adapter import FallbackSearchAdapter

        _lazy_real_file_search_adapter = FallbackSearchAdapter()
    return _lazy_real_file_search_adapter


def _resolve_real_onenote_adapter() -> OneNotePort:
    """Build (and cache) the real `PsBridgeTransport`-backed OneNote
    adapter on first use — never at import time. Mirrors
    `_resolve_real_file_search_adapter()`, though `OneNoteAdapter` never
    imports `win32com` at all (unlike every other real adapter here) — it
    talks to OneNote exclusively through the shared `PsBridgeTransport`'s
    `powershell.exe`/COM bridge (design.md's "Mirror `file_search`'s
    bridge seam" approach), deferred further inside `OneNoteAdapter`'s own
    methods just the same."""
    global _lazy_real_onenote_adapter
    if _lazy_real_onenote_adapter is None:
        from tools.onenote_adapter import OneNoteAdapter

        _lazy_real_onenote_adapter = OneNoteAdapter()
    return _lazy_real_onenote_adapter


def _map_error(exc: Exception) -> ToolError:
    """Map the calendar tool-layer error taxonomy onto FastMCP's `ToolError`,
    preserving a stable `code` prefix so callers can distinguish error kinds
    (design.md's "Error taxonomy" decision)."""
    if isinstance(exc, CalendarToolError):
        entry_ids = getattr(exc, "entry_ids", None)
        suffix = f" (candidates: {entry_ids})" if entry_ids else ""
        return ToolError(f"[{exc.code}] {exc}{suffix}")
    if isinstance(exc, ValueError):
        return ToolError(f"[invalid_request] {exc}")
    return ToolError(str(exc))


def create_server(
    adapter: CalendarPort | None = None,
    task_adapter: TaskPort | None = None,
    mail_adapter: MailPort | None = None,
    file_search_adapter: FileSearchPort | None = None,
    onenote_adapter: OneNotePort | None = None,
    installed: set[str] | None = None,
    shipped: set[str] | None = None,
) -> FastMCP:
    """Build the FastMCP app and register all 3 calendar tools, the 2 task
    tools, the 2 mail tools, the 2 file-search tools, and the 4 OneNote
    tools — narrowed by `shipped` and `installed` (hard-tool-exclusion
    change, mcp-server-bootstrap delta's "Tool Registration" requirement).

    `adapter`/`task_adapter`/`mail_adapter`/`file_search_adapter`/
    `onenote_adapter`: inject a `FakeCalendarAdapter`/`FakeTaskAdapter`/
    `FakeMailAdapter`/`FakeFileSearchAdapter`/`FakeOneNoteAdapter` in
    tests. Left `None` in production so the real Outlook/Windows-Search/
    OneNote adapters are resolved lazily per call.

    `installed`: the enabled tool-name set from `config/installed-
    tools.yaml` (`tools.settings.installed_tools()`). `None` (the
    default — also what `installed_tools()` returns when that file is
    absent) means "no ceiling from this file".

    `shipped`: the tool-name set this deployed package's build actually
    shipped, from `tools/shipped-tools.json` (`tools.settings.shipped_
    tools()`). `None` (the default — also what `shipped_tools()` returns
    when that file is absent, i.e. a legacy package predating hard-tool-
    exclusion) means "no ceiling from this file" — behavior collapses to
    exactly `installed`-only gating, byte-identical to pre-this-change
    behavior.

    `_tool_enabled()` registers a name only when its family's modules are
    physically present (`_FAMILY_PRESENT_BY_TOOL`) AND it clears BOTH
    ceilings — `shipped is None or name in shipped` AND `installed is
    None or name in installed` — the mcp-server-bootstrap delta's full
    precedence table. A name in `installed` but absent from a non-`None`
    `shipped` is silently excluded, never an error (the hard ceiling: a
    hand-edited config cannot resurrect an excluded tool).

    Every module import above stays unconditional per PHYSICALLY PRESENT
    family, regardless of `installed`/`shipped` — only the `@app.tool`
    registration below is gated, via `_tool_enabled()` — so a present-but-
    unshipped/uninstalled tool's code is still shipped-but-disabled, never
    made import-unsafe (design.md Decision 5; the ADDED "Import Safety
    Independent of Registration Gating" requirement). A genuinely ABSENT
    family (its modules never staged at all) is the one case registration
    is gated on physical presence too — see `_FAMILY_PRESENT_BY_TOOL`
    above (design.md Decision 1; the ADDED "Import Safety Under Physical
    Family Absence" requirement).
    """
    app = FastMCP("win-mcp")

    def _tool_enabled(name: str) -> bool:
        if not _FAMILY_PRESENT_BY_TOOL.get(name, True):
            return False
        return (shipped is None or name in shipped) and (installed is None or name in installed)

    def _adapter() -> CalendarPort:
        return adapter if adapter is not None else _resolve_real_adapter()

    def _task_adapter() -> TaskPort:
        return task_adapter if task_adapter is not None else _resolve_real_task_adapter()

    def _mail_adapter() -> MailPort:
        return mail_adapter if mail_adapter is not None else _resolve_real_mail_adapter()

    def _file_search_adapter() -> FileSearchPort:
        return (
            file_search_adapter
            if file_search_adapter is not None
            else _resolve_real_file_search_adapter()
        )

    def _onenote_adapter() -> OneNotePort:
        return onenote_adapter if onenote_adapter is not None else _resolve_real_onenote_adapter()

    if _tool_enabled("calendar_search"):
        @app.tool(name="calendar_search")
        def _calendar_search(
            date_from: Annotated[datetime | None, Field(default=None, alias="from")] = None,
            date_to: Annotated[datetime | None, Field(default=None, alias="to")] = None,
            subject: str | None = None,
            limit: int | None = None,
        ) -> CalendarSearchResult:
            """Search the default Outlook calendar folder by date range and/or
            subject substring. At least one of from/to/subject is required.
            A subject-only query (no explicit from/to) auto-applies a default
            window — 90 days back, 365 days forward from now, configurable via
            `calendar_subject_search_lookback_days`/`..._lookahead_days` —
            since a calendar's value is mostly ahead of today; the window
            actually used is echoed back as `windowApplied` in the response.
            Supplying explicit from/to overrides this window entirely (they
            can widen or narrow the search — caller-controlled). `limit`
            bounds the number of rows returned (optional, default 50, hard
            max 200 — over-max is clamped, not rejected; `<= 0` is
            rejected)."""
            request = SearchRequest(date_from=date_from, date_to=date_to, subject=subject, limit=limit)
            try:
                return calendar_search(request, _adapter())
            except (CalendarToolError, ValueError) as exc:
                raise _map_error(exc) from exc

    if _tool_enabled("calendar_get_event"):
        @app.tool(name="calendar_get_event")
        def _calendar_get_event(
            entry_id: Annotated[str, Field(alias="entryId")],
        ) -> EventDetail:
            """Fetch full detail (including body) for a single event by its
            Outlook entryId."""
            request = GetEventRequest(entry_id=entry_id)
            try:
                return calendar_get_event(request, _adapter())
            except CalendarToolError as exc:
                raise _map_error(exc) from exc

    if _tool_enabled("calendar_get_notes"):
        @app.tool(name="calendar_get_notes")
        def _calendar_get_notes(date: date_, subject: str) -> EventDetail:
            """Resolve the single note-appointment matching date+subject and
            return its full detail (subject + body)."""
            request = GetNotesRequest(date=date, subject=subject)
            try:
                return calendar_get_notes(request, _adapter())
            except CalendarToolError as exc:
                raise _map_error(exc) from exc

    if _tool_enabled("task_search"):
        @app.tool(name="task_search")
        def _task_search(
            date_from: Annotated[datetime | None, Field(default=None, alias="dueFrom")] = None,
            date_to: Annotated[datetime | None, Field(default=None, alias="dueTo")] = None,
            subject: str | None = None,
            status: TaskStatus | None = None,
            include_no_due_date: Annotated[bool, Field(default=True, alias="includeNoDueDate")] = True,
            limit: int | None = None,
        ) -> TaskSearchResult:
            """Search the default Outlook Tasks folder. All filters are
            optional; a filterless call returns every task in the folder (up
            to the effective limit). `limit` bounds the number of rows
            returned (optional, default 50, hard max 200 — over-max is
            clamped, not rejected; `<= 0` is rejected)."""
            request = TaskSearchRequest(
                date_from=date_from,
                date_to=date_to,
                subject=subject,
                status=status,
                include_no_due_date=include_no_due_date,
                limit=limit,
            )
            try:
                return task_search(request, _task_adapter())
            except (CalendarToolError, ValueError) as exc:
                raise _map_error(exc) from exc

    if _tool_enabled("task_get_task"):
        @app.tool(name="task_get_task")
        def _task_get_task(
            entry_id: Annotated[str, Field(alias="entryId")],
        ) -> TaskDetail:
            """Fetch full detail (including body) for a single task by its
            Outlook entryId."""
            request = GetTaskRequest(entry_id=entry_id)
            try:
                return task_get_task(request, _task_adapter())
            except CalendarToolError as exc:
                raise _map_error(exc) from exc

    if _tool_enabled("mail_search"):
        @app.tool(name="mail_search")
        def _mail_search(
            folder: MailFolder | None = None,
            folder_path: Annotated[str | None, Field(default=None, alias="folderPath")] = None,
            date_from: Annotated[datetime | None, Field(default=None, alias="dateFrom")] = None,
            date_to: Annotated[datetime | None, Field(default=None, alias="dateTo")] = None,
            subject: str | None = None,
            sender: str | None = None,
            limit: int | None = None,
        ) -> MailSearchResult:
            """Search the default Outlook Inbox, Sent Items, or Drafts folder
            (`folder`), or an arbitrary custom folder resolved from the default
            mail store's root (`folderPath`, a `/`-delimited path) — exactly one
            of `folder`/`folderPath` is required. Also filters by date range,
            subject substring, and/or sender substring; at least one of
            dateFrom/dateTo/subject/sender is required. `limit` bounds the
            number of rows returned (optional, default 50, hard max 200 —
            over-max is clamped, not rejected; `<= 0` is rejected)."""
            try:
                request = MailSearchRequest(
                    folder=folder,
                    folder_path=folder_path,
                    date_from=date_from,
                    date_to=date_to,
                    subject=subject,
                    sender=sender,
                    limit=limit,
                )
                return mail_search(request, _mail_adapter())
            except (CalendarToolError, ValueError) as exc:
                raise _map_error(exc) from exc

    if _tool_enabled("mail_get_message"):
        @app.tool(name="mail_get_message")
        def _mail_get_message(
            entry_id: Annotated[str, Field(alias="entryId")],
            include_html_body: Annotated[
                bool, Field(default=False, alias="includeHtmlBody")
            ] = False,
        ) -> MessageDetail:
            """Fetch full detail (including body) for a single Inbox/Sent
            Items/Drafts/folderPath message by its Outlook entryId.
            `attachmentNames` is always populated; `htmlBody` is populated only
            when `includeHtmlBody=true` is passed (default `false`)."""
            request = GetMessageRequest(entry_id=entry_id, include_html_body=include_html_body)
            try:
                return mail_get_message(request, _mail_adapter())
            except CalendarToolError as exc:
                raise _map_error(exc) from exc

    if _tool_enabled("file_search"):
        @app.tool(name="file_search")
        def _file_search(
            filename: str | None = None,
            phrase: str | None = None,
            scope: str | None = None,
        ) -> FileSearchResponse:
            """Search by a case-insensitive `filename` substring (answered by a
            bounded filesystem walk, independent of the Windows Search index)
            and/or a full-text `phrase` match (answered by the index: ADO,
            then a PowerShell bridge on ADO failure), optionally restricted to
            an absolute `scope` subtree. At least one of filename/phrase is
            required; `scope` (if given) must fall within a configured or
            default allowed search root. Returns `results` plus a
            `resultsTruncated` flag."""
            request = FileSearchRequest(filename=filename, phrase=phrase, scope=scope)
            try:
                return file_search(request, _file_search_adapter())
            except (CalendarToolError, ValueError) as exc:
                raise _map_error(exc) from exc

    if _tool_enabled("file_get_info"):
        @app.tool(name="file_get_info")
        def _file_get_info(path: str) -> FileDetail:
            """Fetch full indexed metadata for a single file by its native path
            or `file:///`-style URL form, as previously returned by
            `file_search`. `path` must fall within a configured or default
            allowed search root."""
            request = GetFileInfoRequest(path=path)
            try:
                return file_get_info(request, _file_search_adapter())
            except CalendarToolError as exc:
                raise _map_error(exc) from exc

    if _tool_enabled("onenote_search"):
        @app.tool(name="onenote_search")
        def _onenote_search(query: str, limit: int | None = None) -> list[PageSummary]:
            """Full-text search over OneNote page content (`FindPages`
            via the COM bridge). `query` must be non-empty — rejected as an
            `[invalid_request]` error before any adapter call. `limit` bounds
            the number of rows returned (optional, default 50, hard max 200 —
            over-max is clamped, not rejected; `<= 0` is rejected). An empty
            result is `[]`, not an error.

            INDEX-BACKED, titles and body both: results come from OneNote's
            search index, and a page the index has not picked up yet — e.g.
            one created recently in the UI — is silently absent even though
            it exists and renders. A missing expected page is not proof the
            page is gone; it may simply be unindexed (live-verified
            2026-08-31: a 3-day-old page invisible to every query, present
            in the hierarchy)."""
            request = OneNoteSearchRequest(query=query, limit=limit)
            try:
                return onenote_search(request, _onenote_adapter())
            except (CalendarToolError, ValueError) as exc:
                raise _map_error(exc) from exc

    if _tool_enabled("onenote_get_page"):
        @app.tool(name="onenote_get_page")
        def _onenote_get_page(
            page_id: Annotated[str, Field(alias="pageId")],
        ) -> PageDetail:
            """Fetch full, read-only text detail for a single OneNote page by
            its `pageId` (as returned by `onenote_search`). Never mutates any
            notebook/section/page state. Only COM `pageId`s resolve here: the
            GUIDs inside a OneNote web/SharePoint "Copy Link to Page" URL are
            a DIFFERENT id space and return `[onenote_page_not_found]`
            (live-verified 2026-08-31).

            `bodyText` is a FLATTENED plain-text reading view of the page —
            bullets, indentation, tables and images render as plain lines. It
            is not the storage format: `onenote_update_page` appends and never
            writes this flattened text back over the page, so reading a
            formatted page is always safe. `bodyTextIncomplete: true` means
            the page contains tables, images or ink that this flattened view
            cannot represent — the page holds more than you are seeing;
            updating it is still safe. `lastModifiedDateTime` is the value
            `onenote_update_page`'s conflict guard expects — pass it back
            exactly as returned."""
            request = GetPageRequest(page_id=page_id)
            try:
                return onenote_get_page(request, _onenote_adapter())
            except CalendarToolError as exc:
                raise _map_error(exc) from exc

    if _tool_enabled("onenote_list_sections"):
        @app.tool(name="onenote_list_sections")
        def _onenote_list_sections() -> list[SectionInfo]:
            """List every OneNote notebook/section pair with its canonical
            ids. `sectionId` (the `{GUID}{1}{B0}` form) is what
            `onenote_create_page` requires — a bare GUID or a section NAME
            will never resolve. Read-only; never mutates any state."""
            try:
                return onenote_list_sections(_onenote_adapter())
            except CalendarToolError as exc:
                raise _map_error(exc) from exc

    if _tool_enabled("onenote_list_pages"):
        @app.tool(name="onenote_list_pages")
        def _onenote_list_pages(
            section_id: Annotated[str, Field(alias="sectionId")],
        ) -> list[PageSummary]:
            """List every page of one OneNote section, straight from the
            hierarchy — NOT the search index, so it includes pages
            `onenote_search` cannot return yet (the index silently omits
            recently created pages; live-verified 2026-08-31). This is the
            reliable route to a `pageId` when search comes up empty.
            `sectionId` is the canonical `{GUID}{1}{B0}` form returned by
            `onenote_list_sections`; a bare GUID or a section name will
            never resolve. Pages come back in notebook order. An empty
            section is `[]`, not an error. Read-only; never mutates any
            state. `lastModifiedDateTime` here is hierarchy-sourced and can
            lag the page's true value — call `onenote_get_page` for the
            write-grade timestamp `onenote_update_page`'s conflict guard
            expects."""
            request = ListPagesRequest(section_id=section_id)
            try:
                return onenote_list_pages(request, _onenote_adapter())
            except CalendarToolError as exc:
                raise _map_error(exc) from exc

    if _tool_enabled("onenote_create_page"):
        @app.tool(name="onenote_create_page")
        def _onenote_create_page(
            section_id: Annotated[str, Field(alias="sectionId")],
            title: str,
            body_text: Annotated[str, Field(alias="bodyText")],
        ) -> PageDetail:
            """Create a new page in the OneNote section identified by
            `sectionId` — the canonical `{GUID}{1}{B0}` form returned by
            `onenote_list_sections` (also on `onenote_search` rows); a bare
            GUID or a section name will never resolve. `bodyText` is written
            as one plain-text paragraph. The section's owning notebook is
            resolved and checked against the writable-notebook allowlist
            (`onenote_writable_notebooks`, default `["z - Test Notebook"]`)
            before any write is attempted — refused with a clear
            `[onenote_notebook_not_allowed]` error otherwise."""
            request = CreatePageRequest(section_id=section_id, title=title, body_text=body_text)
            try:
                return onenote_create_page(request, _onenote_adapter())
            except CalendarToolError as exc:
                raise _map_error(exc) from exc

    if _tool_enabled("onenote_update_page"):
        @app.tool(name="onenote_update_page")
        def _onenote_update_page(
            page_id: Annotated[str, Field(alias="pageId")],
            body_text: Annotated[str, Field(alias="bodyText")],
            expected_last_modified: Annotated[
                datetime | None, Field(alias="dateExpectedLastModified")
            ] = None,
        ) -> PageDetail:
            """APPEND `bodyText` as one new plain-text paragraph at the end of
            the OneNote page identified by `pageId`. Never replaces or
            reformats existing content — the page's original formatting
            (bullets, tables, images) is preserved untouched, so updating a
            formatted page is safe.

            `dateExpectedLastModified` is a conflict guard, not a write-back
            of the read body: pass `lastModifiedDateTime` exactly as
            `onenote_get_page` returned it, and a mismatch (the page changed
            since your read) raises `[onenote_page_conflict]` — re-read and
            retry with the fresh value. OMIT the field for an UNGUARDED
            overwrite (no concurrency check at all): the escape hatch for a
            page that keeps rejecting a freshly-read value, which OneNote's
            lazily-stamped timestamps can cause on pages not written recently.
            The page's owning notebook is checked against the
            writable-notebook allowlist before any write, same as
            `onenote_create_page`."""
            request = UpdatePageRequest(
                page_id=page_id,
                body_text=body_text,
                expected_last_modified=expected_last_modified,
            )
            try:
                return onenote_update_page(request, _onenote_adapter())
            except CalendarToolError as exc:
                raise _map_error(exc) from exc

    if _tool_enabled("server_info"):
        @app.tool(name="server_info")
        def _server_info() -> DeploymentInfo:
            """Identify this deployment: package name, build UTC and build
            id from the build stamp (`build-info.json`; null with a `note`
            for a source checkout or a pre-stamp package), install root
            (distinguishes the PRO and QA installs), Python version, and
            the tool names this server process actually registered.
            Read-only, touches no Outlook/OneNote/file state. Call it
            FIRST when verifying that a redeployed build is the one
            answering — a server started before a promote keeps running
            the old code until its client restarts."""
            enabled = [name for name in _FAMILY_PRESENT_BY_TOOL if _tool_enabled(name)]
            return deployment_info(enabled)

    return app


def _force_utf8_stdio() -> None:
    """Belt-and-braces fix for a confirmed real-Windows bug: Windows Python
    encodes stdout/stdin/stderr in the legacy console codepage by default
    (not UTF-8), which silently corrupts the UTF-8 JSON-RPC wire protocol —
    observed in practice as mojibake in accented event subjects (e.g.
    "Reunión", "Café" rendered as "Reuni?n", "Caf?"). WinMCP.bat
    also sets `PYTHONUTF8=1` before invoking python; this function is the
    second, in-process line of defense so the fix holds even if the server
    is ever launched a different way.

    Reconfigures each stream to UTF-8 only if it exposes `.reconfigure()`
    (Python 3.7+ text streams do); silently skipped otherwise so this never
    breaks tests or non-reconfigurable streams on Linux or elsewhere.
    """
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
            except Exception:
                pass


def main() -> None:
    """Entrypoint: run the server over stdio only (no network listener, no
    auth), per mcp-server-bootstrap spec's "Transport and Access Scope".

    Resolves `installed` from `tools.settings.installed_tools()` — `None`
    when `config/installed-tools.yaml` is absent (no ceiling from this
    file), otherwise the enabled subset the installer wrote (selective-
    tool-deployment change). Resolves `shipped` from `tools.settings.
    shipped_tools()` — `None` when `tools/shipped-tools.json` is absent
    (legacy package predating hard-tool-exclusion; no ceiling from this
    file either), otherwise the exact tool-name set this build's manifest
    lists (hard-tool-exclusion change)."""
    _force_utf8_stdio()
    create_server(
        installed=settings.installed_tools(), shipped=settings.shipped_tools()
    ).run(transport="stdio")


if __name__ == "__main__":
    main()
