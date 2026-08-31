"""Typed error taxonomy for the Outlook calendar adapter/tool layer.

Raw COM errors (`pywintypes.com_error`) are opaque to an LLM caller. These
three exceptions give the adapter a small, stable vocabulary that the tool
layer (`tools/calendar.py`) can catch and map to a clear MCP tool error with
a stable `code` field, instead of letting a bare/unhandled COM exception
propagate. See design.md's "Error taxonomy" decision.
"""


class CalendarToolError(Exception):
    """Base class for the typed calendar error taxonomy.

    Subclasses set `code` as a class attribute — a stable, machine-readable
    identifier the tool layer uses to build the MCP tool error payload.
    """

    code: str = "calendar_tool_error"


class OutlookUnavailableError(CalendarToolError):
    """Raised when the adapter cannot reach Outlook at all.

    Simulates `win32com.client.Dispatch("Outlook.Application")` failing
    because Outlook is not installed or not running.
    """

    code = "outlook_unavailable"


class EventNotFoundError(CalendarToolError):
    """Raised when an `entryId` does not resolve to a calendar item.

    Simulates Outlook's `GetItemFromID` returning nothing / raising for an
    unknown or invalid entryId.
    """

    code = "event_not_found"


class AmbiguousMatchError(CalendarToolError):
    """Raised when a date/subject lookup matches more than one event.

    Carries the candidate `entry_ids` so the caller can disambiguate via
    `calendar_search` + `calendar_get_event` instead of an arbitrary pick.
    """

    code = "ambiguous_match"

    def __init__(self, message: str, *, entry_ids: list[str]):
        super().__init__(message)
        self.entry_ids = entry_ids


class TaskNotFoundError(CalendarToolError):
    """Raised when an `entryId` does not resolve to an Outlook Task item.

    Simulates Outlook's `GetItemFromID` returning nothing / raising for an
    unknown or invalid entryId. Reuses the `CalendarToolError` taxonomy per
    design.md's "Error taxonomy reuse" decision, rather than introducing a
    separate task-specific base class.
    """

    code = "task_not_found"


class MessageNotFoundError(CalendarToolError):
    """Raised when an `entryId` does not resolve to an Inbox/Sent Items
    message.

    Simulates Outlook's `GetItemFromID` returning nothing / raising for an
    unknown or invalid entryId. Reuses the `CalendarToolError` taxonomy per
    the outlook-mail-read change's design.md "Error taxonomy" decision,
    rather than introducing a separate `MailToolError` base class.
    """

    code = "message_not_found"


class MailFolderNotFoundError(CalendarToolError):
    """Raised when a `folderPath` segment does not resolve to a subfolder
    of the default mail store.

    Simulates a failed per-segment `Folders.Item(name)` traversal (see the
    mail-reading-depth change's design.md's "Segment resolution" decision).
    Carries `path` (the full requested `folderPath`) and `failing_segment`
    (the specific segment that did not resolve), mirroring
    `AmbiguousMatchError`'s precedent of carrying structured context beyond
    the message string.
    """

    code = "mail_folder_not_found"

    def __init__(self, message: str, *, path: str, failing_segment: str):
        super().__init__(message)
        self.path = path
        self.failing_segment = failing_segment


class SearchRootNotAllowedError(CalendarToolError):
    """Raised when a `file_search`/`file_get_info` request's `scope`/`path`
    (or, when omitted, the unrestricted query) is not contained within a
    configured or default `file_search_allowed_roots` entry.

    Carries `requested_path` (the path/scope that failed containment) and
    `allowed_roots` (the roots it was checked against), mirroring
    `AmbiguousMatchError`/`MailFolderNotFoundError`'s precedent of carrying
    structured context beyond the message string. Raised by the tool layer
    (`tools/file_search.py`, a later batch) before any adapter call — see
    design.md's "Roots-enforcement layering" decision.
    """

    code = "search_root_not_allowed"

    def __init__(self, message: str, *, requested_path: str, allowed_roots: list[str]):
        super().__init__(message)
        self.requested_path = requested_path
        self.allowed_roots = allowed_roots


class FileNotFoundInIndexError(CalendarToolError):
    """Raised when a `file_get_info` `path` does not resolve to any item in
    the Windows Search index.

    Simulates the adapter's `get_info()` finding no matching row — never an
    unhandled crash or a silently empty/default response, per the
    file-get-info spec's "File Not Found In Index" requirement.
    """

    code = "file_not_found_in_index"


class WindowsSearchUnavailableError(CalendarToolError):
    """Raised when the adapter cannot reach the Windows Search index at
    all.

    Simulates `ADODB.Connection.Open`/`Recordset.Open` raising (e.g. the
    Windows Search service is not running), per the windows-search-adapter
    spec's "Connection Failure Raises a Typed Error" requirement.
    """

    code = "windows_search_unavailable"


class PathNotFoundError(CalendarToolError):
    """Raised by `file_get_info` when `path` (after the roots check and any
    `file:///`/native normalization) does not resolve to an existing file
    or directory on disk — checked via `os.stat` before any index
    enrichment is attempted.

    Distinct from `FileNotFoundInIndexError`: a `path_not_found` result
    means "your path is wrong," while an unindexed-but-real path (index
    enrichment simply missing/unavailable) never raises at all — see the
    file-search-resilience change's file-get-info spec's "Path Not Found
    On Disk" and "Index Enrichment Failure Never Surfaces" requirements.
    """

    code = "path_not_found"


class OneNoteUnavailableError(CalendarToolError):
    """Raised when the adapter cannot reach OneNote/the PowerShell bridge
    at all.

    Simulates a bridge spawn failure, malformed output, or a
    script-reported error other than an unresolved page/section id, per
    the onenote-com-adapter spec's "Failure Mapping" requirement — the
    add-onenote-adapter change's `CalendarToolError`-taxonomy-reuse
    decision (design.md's "Error taxonomy" decision), same as
    `WindowsSearchUnavailableError`/`OutlookUnavailableError`.
    """

    code = "onenote_unavailable"


class OneNotePageNotFoundError(CalendarToolError):
    """Raised when a `pageId` does not resolve to a OneNote page.

    Simulates `GetPageContent`/`UpdatePageContent` reporting an unresolved
    page id, or the bridge returning zero rows for a `get_page` request,
    per the onenote-com-adapter spec's "Failure Mapping" requirement.
    """

    code = "onenote_page_not_found"


class OneNoteSectionNotFoundError(CalendarToolError):
    """Raised when a `sectionId` does not resolve to a OneNote section in
    the notebook/section hierarchy.

    Reuses the `CalendarToolError` taxonomy per design.md's "Error
    taxonomy" decision.
    """

    code = "onenote_section_not_found"


class OneNoteWriteNotAllowedError(CalendarToolError):
    """Raised when a `onenote_create_page`/`onenote_update_page` target's
    notebook is not in the configured `onenote_writable_notebooks`
    allowlist.

    Carries `notebook_name` (the target's resolved notebook) and
    `allowed_notebooks` (the allowlist it was checked against), mirroring
    `SearchRootNotAllowedError`'s precedent of carrying structured context
    beyond the message string. Raised by the tool layer
    (`tools/onenote.py`, a later batch) before any adapter/COM call — see
    the onenote-write-page spec's "Writable Notebook Allowlist"
    requirement.
    """

    code = "onenote_notebook_not_allowed"

    def __init__(self, message: str, *, notebook_name: str, allowed_notebooks: list[str]):
        super().__init__(message)
        self.notebook_name = notebook_name
        self.allowed_notebooks = allowed_notebooks


class OneNotePageConflictError(CalendarToolError):
    """Raised when `onenote_update_page`'s `dateExpectedLastModified` is
    older than the page's real last-modified time — `UpdatePageContent`'s
    optimistic-concurrency check per the onenote-write-page spec's
    "Conflicting Update Raises, Never Silently Overwrites" requirement.
    Never a silent overwrite.
    """

    code = "onenote_page_conflict"
