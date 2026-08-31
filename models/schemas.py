"""Pydantic request/response schemas for the Outlook calendar MCP tools.

`EventSummary`/`EventDetail` are the response shapes returned to MCP clients.
`SearchRequest`/`GetEventRequest`/`GetNotesRequest` are the validated tool
input shapes. Field aliases match the wire/JSON casing used in specs.md
(`entryId`, `from`, `to`) while the Python-side attribute names stay
snake_case; `populate_by_name=True` lets code construct instances either way.
"""
from datetime import date as date_
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _AliasedModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class _TruncatableResult(_AliasedModel):
    """Shared mixin for the search-result-caps change's (BUG-002) three
    response envelopes — `MailSearchResult`/`CalendarSearchResult`/
    `TaskSearchResult` — per design.md's "Response envelope shape"
    decision: `results_truncated` is `true` when the effective `limit`
    (see `tools/settings.py::resolve_search_limit()`) cut the true match
    count, `false` otherwise. Mirrors `FileSearchResponse`'s
    `results_truncated` field/alias (file-search-resilience change), kept
    as a separate mixin here rather than reused directly since
    `FileSearchResponse` lives in the disjoint file-search domain."""

    results_truncated: bool = Field(default=False, alias="resultsTruncated")


class EventSummary(_AliasedModel):
    """Lightweight calendar item as returned by `calendar_search`."""

    entry_id: str = Field(alias="entryId")
    subject: str
    start: datetime
    end: datetime

    @field_validator("start", "end")
    @classmethod
    def _require_tz_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("datetime must be timezone-aware")
        return value


class EventDetail(EventSummary):
    """Full calendar item detail as returned by `calendar_get_event`."""

    body: str


class SearchRequest(_AliasedModel):
    """Input for `calendar_search`. `limit` (search-result-caps change,
    BUG-002) bounds the number of `EventSummary` rows returned — optional,
    default `50`, hard max `200`, resolved via
    `tools/settings.py::resolve_search_limit()` at the tool layer (never
    validated here, so an over-max value round-trips through this schema
    unclamped until the tool layer resolves it)."""

    date_from: datetime | None = Field(default=None, alias="from")
    date_to: datetime | None = Field(default=None, alias="to")
    subject: str | None = None
    limit: int | None = None


class GetEventRequest(_AliasedModel):
    """Input for `calendar_get_event`."""

    entry_id: str = Field(alias="entryId")


class GetNotesRequest(_AliasedModel):
    """Input for `calendar_get_notes`."""

    date: date_
    subject: str


class SearchWindow(_AliasedModel):
    """The concrete `from`/`to` window `calendar_search` auto-applied to a
    subject-only request (BUG-008 hotfix, 2026-08-26). Populated on
    `CalendarSearchResult.window_applied` ONLY when the caller gave no
    explicit `from`/`to` and the tool silently filled one in — so an empty
    result can never again be mistaken for "no such appointment" when it
    was really "outside a window the caller was never told about"."""

    date_from: datetime = Field(alias="from")
    date_to: datetime = Field(alias="to")


class CalendarSearchResult(_TruncatableResult):
    """Response envelope for `calendar_search` (search-result-caps change,
    BUG-002) — wraps the `EventSummary` list with a response-level
    `results_truncated` flag, per design.md's "Response envelope shape"
    decision. Replaces the previous plain `list[EventSummary]` return.

    `window_applied` (BUG-008 hotfix, 2026-08-26) is `None` unless the
    request was subject-only (no explicit `from`/`to`), in which case it
    echoes back the auto-applied default window so the caller can tell
    "not found" from "outside a window it never asked for"."""

    results: list[EventSummary]
    window_applied: SearchWindow | None = Field(default=None, alias="windowApplied")


class TaskStatus(str, Enum):
    """Mirrors COM's `OlTaskStatus` 1:1 (see design.md's "Status mapping" decision)."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    WAITING = "waiting"
    DEFERRED = "deferred"
    COMPLETED = "completed"


class TaskSummary(_AliasedModel):
    """Lightweight Outlook Task / To Do item as returned by `task_search`."""

    entry_id: str = Field(alias="entryId")
    subject: str
    due_date: datetime | None = Field(default=None, alias="dueDate")
    status: TaskStatus
    is_complete: bool = Field(alias="isComplete")


class TaskDetail(TaskSummary):
    """Full Outlook Task / To Do item detail as returned by `task_get_task`."""

    body: str


class TaskSearchRequest(_AliasedModel):
    """Input for `task_search`. Unlike `SearchRequest`, all fields are
    optional — see design.md's "No-due-date search filtering" decision.
    `limit` (search-result-caps change, BUG-002) bounds the number of
    `TaskSummary` rows returned — optional, default `50`, hard max `200`,
    resolved via `tools/settings.py::resolve_search_limit()` at the tool
    layer."""

    date_from: datetime | None = Field(default=None, alias="dueFrom")
    date_to: datetime | None = Field(default=None, alias="dueTo")
    subject: str | None = None
    status: TaskStatus | None = None
    include_no_due_date: bool = Field(default=True, alias="includeNoDueDate")
    limit: int | None = None


class GetTaskRequest(_AliasedModel):
    """Input for `task_get_task`."""

    entry_id: str = Field(alias="entryId")


class TaskSearchResult(_TruncatableResult):
    """Response envelope for `task_search` (search-result-caps change,
    BUG-002) — wraps the `TaskSummary` list with a response-level
    `results_truncated` flag, per design.md's "Response envelope shape"
    decision. Replaces the previous plain `list[TaskSummary]` return."""

    results: list[TaskSummary]


class MailFolder(str, Enum):
    """The Outlook mail folders `mail_search`/`mail_get_message` cover (see
    design.md's "Folder parameterization" decision — one MailPort instead
    of separate per-folder ports). `DRAFTS` was added for the
    mail-reading-depth change alongside `folderPath` (an arbitrary
    `/`-delimited path — see `MailSearchRequest.folder_path` — for folders
    outside this fixed enum)."""

    INBOX = "inbox"
    SENT = "sent"
    DRAFTS = "drafts"


class MessageSummary(_AliasedModel):
    """Lightweight Outlook Inbox/Sent Items message as returned by
    `mail_search`.

    `sender`/`sender_address` are folder-relative — see design.md's "Sender
    filter/field asymmetry" decision: for `folder="inbox"` they carry
    `SenderName`/`SenderEmailAddress`; for `folder="sent"` they carry the
    recipient (`To`) name/address instead, since Outlook does not populate
    a meaningful sender for items the user sent. One reused field pair keeps
    `MessageSummary` stable across both folders.
    """

    entry_id: str = Field(alias="entryId")
    subject: str
    sender: str
    sender_address: str = Field(alias="senderAddress")
    date: datetime
    has_attachments: bool = Field(alias="hasAttachments")


class MessageDetail(MessageSummary):
    """Full Inbox/Sent Items message detail as returned by
    `mail_get_message`. `body` is always the plain-text `MailItem.Body`,
    never `HTMLBody`. `attachment_names`/`html_body` were added for the
    mail-reading-depth change — see that change's mail-get-detail spec's
    "Get Message Input/Output" requirement. `attachment_names` is always
    populated (empty list when there are no attachments); `html_body` is
    `None` unless `GetMessageRequest.include_html_body` was `True`."""

    body: str
    to: list[str]
    attachment_names: list[str] = Field(default_factory=list, alias="attachmentNames")
    html_body: str | None = Field(default=None, alias="htmlBody")


class MailSearchRequest(_AliasedModel):
    """Input for `mail_search`. `folder` and `folder_path` (added for the
    mail-reading-depth change) are mutually exclusive selectors — see that
    change's mail-search spec's "Search Input Parameters" requirement:
    exactly one of them MUST be provided. `folder_path` is an arbitrary
    `/`-delimited path resolved relative to the default mail store's
    folder tree, for folders outside the fixed `MailFolder` enum.
    (Previously: `folder` alone was required.)

    `limit` (search-result-caps change, BUG-002) bounds the number of
    `MessageSummary` rows returned — optional, default `50`, hard max
    `200`, resolved via `tools/settings.py::resolve_search_limit()` at the
    tool layer."""

    folder: MailFolder | None = None
    folder_path: str | None = Field(default=None, alias="folderPath")
    date_from: datetime | None = Field(default=None, alias="dateFrom")
    date_to: datetime | None = Field(default=None, alias="dateTo")
    subject: str | None = None
    sender: str | None = None
    limit: int | None = None

    @model_validator(mode="after")
    def _exactly_one_folder_selector(self) -> "MailSearchRequest":
        if (self.folder is None) == (self.folder_path is None):
            raise ValueError("exactly one of folder or folderPath is required")
        return self


class GetMessageRequest(_AliasedModel):
    """Input for `mail_get_message`. `include_html_body` was added for the
    mail-reading-depth change — see that change's mail-get-detail spec's
    "Get Message Input/Output" requirement. Defaults to `False`, so
    `htmlBody` is omitted/`None` unless explicitly requested."""

    entry_id: str = Field(alias="entryId")
    include_html_body: bool = Field(default=False, alias="includeHtmlBody")


class MailSearchResult(_TruncatableResult):
    """Response envelope for `mail_search` (search-result-caps change,
    BUG-002) — wraps the `MessageSummary` list with a response-level
    `results_truncated` flag, per design.md's "Response envelope shape"
    decision. Replaces the previous plain `list[MessageSummary]` return."""

    results: list[MessageSummary]


class FileSearchRequest(_AliasedModel):
    """Input for `file_search` (file-search change). `filename` is a
    case-insensitive substring match on `System.FileName`; `phrase` is a
    full-text `CONTAINS()` match on file content/properties; `scope` is an
    absolute path constraining the search to that subtree. All three
    fields are single-word, so no camelCase alias differs from the
    snake_case attribute name.

    Unlike `MailSearchRequest`'s "exactly one of folder/folderPath"
    `model_validator`, this schema does NOT enforce "at least one of
    filename/phrase" here — the file-search spec's "Both filename and
    phrase omitted is rejected" scenario calls for a plain `ValueError`
    raised by the tool layer (`tools/file_search.py`, a later batch)
    before any adapter call, not a pydantic `ValidationError` at
    construction time.
    """

    filename: str | None = None
    phrase: str | None = None
    scope: str | None = None


class GetFileInfoRequest(_AliasedModel):
    """Input for `file_get_info` (file-search change). `path` accepts
    either the native `System.ItemPathDisplay` form or the `file:///`-style
    `System.ItemUrl` form previously returned by `file_search` — see the
    file-get-info spec's "Get Info Input Parameters" requirement."""

    path: str


class FileSummary(_AliasedModel):
    """Lightweight file result as returned by `file_search` (file-search
    change). `path` is the normalized native-form path — see the
    windows-search-adapter spec's "Path Representation Normalization"
    requirement — never a raw `ItemUrl`. `kind`/`extension` are additions
    beyond the file-search spec's minimum output shape (`path`/`name`/
    `size`/`lastModified`), carried per design.md's Interfaces/Contracts
    section since the adapter's `SELECT` already fetches `System.Kind`/
    `System.FileExtension` for free. Excludes content per the file-search
    spec's "Search Output Shape" requirement.

    `alt_url_path` (alias-containment-hotfix) is internal-only — never
    serialized (`exclude=True`) — the `System.ItemUrl`-decoded native form
    of this row's path, populated by the adapter's row mapping
    (`tools/file_search_adapter.py::_row_to_summary`/`_row_from_mapping`)
    alongside `path` regardless of which form `path` itself preferred.
    Windows Search can report a redirected-library alias in
    `System.ItemPathDisplay` (e.g. a `Documents` library shortcut into a
    OneDrive-synced tree) while `System.ItemUrl` still resolves to the
    real, containable path underneath. `tools/file_search.py`'s post-call
    allowed-roots filter (`_drop_outside_allowed_roots`) reads this to
    keep a row whose `path` (the alias) fails containment but whose
    `alt_url_path` (the real path) passes, rewriting the returned `path`
    to the real form in that case. `None` when `System.ItemUrl` was
    absent on the row (nothing to fall back to)."""

    path: str
    name: str
    size: int
    last_modified: datetime = Field(alias="lastModified")
    kind: str | None = None
    extension: str | None = None
    alt_url_path: str | None = Field(default=None, exclude=True)


class FileSearchResponse(_AliasedModel):
    """Response envelope for `file_search` (file-search-resilience change).
    Wraps the `FileSummary` list with a response-level `results_truncated`
    flag — `true` when the filesystem walk (see the filesystem-walk-search
    spec) stopped early due to a result/time/directory cap, `false`
    otherwise. This is a response-level flag (one per search call), not a
    per-`FileSummary` field, per the file-search spec's MODIFIED "Search
    Output Shape" requirement. `tools/file_search.py`'s dispatch rewrite
    and `server.py`'s tool return-type change to use this envelope are a
    later batch's work (Phase 5/6) — this batch only introduces the model.
    """

    results: list["FileSummary"]
    results_truncated: bool = Field(default=False, alias="resultsTruncated")


class FileDetail(FileSummary):
    """Full file detail as returned by `file_get_info` (file-search
    change). Adds `created_time` (required — see the file-get-info spec's
    "Get Info Output Shape" requirement) and `snippet` (optional
    content-derived text, `None` when not indexed or for a locally-synced
    OneDrive Files-On-Demand placeholder that has not been hydrated — see
    that spec's "OneDrive Placeholder Metadata" requirement). `FileDetail`
    IS-A `FileSummary`, mirroring `EventDetail`/`MessageDetail`."""

    created_time: datetime = Field(alias="createdTime")
    snippet: str | None = None


class PageSummary(_AliasedModel):
    """Lightweight OneNote page as returned by `onenote_search`
    (add-onenote-adapter change). `last_modified` is optional — the
    onenote-search spec's "Search Input/Output" requirement notes it is
    omitted when the bridge does not report it for a row (unlike
    `EventSummary.start`/`end`, which are always required).

    `notebook_id`/`section_id` (onenote/0003 mailbox round, defect 2):
    the write path needs a real OneNote section id (`{GUID}{1}{B0}` form)
    and nothing returned it, so callers had to guess — returning the ids
    the bridge already walks past costs nothing and makes the write path
    self-serving from a read. Optional because older bridge rows (and
    some fake fixtures) do not carry them."""

    page_id: str = Field(alias="pageId")
    title: str
    notebook_name: str = Field(alias="notebookName")
    section_name: str = Field(alias="sectionName")
    notebook_id: str | None = Field(default=None, alias="notebookId")
    section_id: str | None = Field(default=None, alias="sectionId")
    last_modified: datetime | None = Field(default=None, alias="lastModifiedDateTime")


class PageDetail(PageSummary):
    """Full OneNote page detail as returned by `onenote_get_page`/
    `onenote_create_page`/`onenote_update_page`. `body_text` is plain text
    with paragraphs joined — see the onenote-com-adapter spec's "Page
    Content Extraction" requirement. `PageDetail` IS-A `PageSummary`,
    mirroring `EventDetail`/`MessageDetail`/`FileDetail`.

    `body_text_incomplete` (onenote/0024+0027): `True` when the page's XML
    contains structure the flattened `body_text` cannot represent —
    tables, images, or ink. It flags the READ as lossy; writes stay
    allowed regardless, since `onenote_update_page` round-trips the
    page's original XML and appends (it never writes the flattened text
    back). Nested outlines/bullets degrade gracefully and do NOT set it."""

    body_text: str = Field(alias="bodyText")
    body_text_incomplete: bool = Field(default=False, alias="bodyTextIncomplete")


class DeploymentInfo(_AliasedModel):
    """Response of `server_info` (add-server-info change, cowork mailbox
    request 2026-08-28): the deployment identifies ITSELF — build stamp
    from `build-info.json` (null fields + `note` when absent: source
    checkout or pre-stamp package), install root (PRO vs QA vs checkout),
    and the tool names this server process actually registered. Exists so
    a debugging client can state which build answered instead of
    inferring it from behavioral tells after a promote without a client
    restart."""

    package: str | None = None
    built_utc: str | None = Field(default=None, alias="builtUtc")
    build_id: str | None = Field(default=None, alias="buildId")
    build_mode: str | None = Field(default=None, alias="buildMode")
    install_root: str = Field(alias="installRoot")
    python_version: str = Field(alias="pythonVersion")
    enabled_tools: list[str] = Field(alias="enabledTools")
    note: str | None = None


class SectionInfo(_AliasedModel):
    """One notebook/section pair as returned by `onenote_list_sections`
    (onenote/0003 mailbox round, defect 2): the canonical section id
    (`{GUID}{1}{B0}` form) that `onenote_create_page` requires, which no
    other tool surface exposed — callers had nothing to go on but
    OneNote's undocumented object-id grammar."""

    notebook_id: str = Field(alias="notebookId")
    notebook_name: str = Field(alias="notebookName")
    section_id: str = Field(alias="sectionId")
    section_name: str = Field(alias="sectionName")


class OneNoteSearchRequest(_AliasedModel):
    """Input for `onenote_search`. Like `FileSearchRequest`, does NOT
    enforce "query is non-empty" or clamp `limit` at the schema level —
    the onenote-search spec's "Empty query is rejected before any adapter
    call" and "Result Limit Parameter" requirements call for the tool
    layer (`tools/onenote.py`, a later batch) to raise a plain
    `ValueError`/clamp, not a pydantic `ValidationError` here."""

    query: str
    limit: int | None = None


class GetPageRequest(_AliasedModel):
    """Input for `onenote_get_page`."""

    page_id: str = Field(alias="pageId")


class CreatePageRequest(_AliasedModel):
    """Input for `onenote_create_page`. `section_id` is resolved by the
    tool layer (a later batch) from a notebook/section name pair, checked
    against `onenote_writable_notebooks` before this request is ever
    honored — see the onenote-write-page spec's "Writable Notebook
    Allowlist" requirement."""

    section_id: str = Field(alias="sectionId")
    title: str
    body_text: str = Field(alias="bodyText")


class UpdatePageRequest(_AliasedModel):
    """Input for `onenote_update_page`. `expected_last_modified` is the
    optimistic-concurrency guard: when present it must EQUAL the page's
    stored last-modified time or the write is refused (the onenote-write-
    page spec's "Update Page Requires Optimistic Concurrency" requirement
    — a supplied value is never silently replaced by one that would pass).

    It is now OPTIONAL (onenote/0005 mailbox round): OneNote keeps two
    last-modified values per page that diverge minutes after a write
    settles, so a caller who read the freshest obtainable value can still
    be refused with nothing left to try. Omitting the field is the
    documented escape hatch — an UNGUARDED overwrite (one-argument
    `UpdatePageContent`, no concurrency check at all), never a bypass the
    server invents on the caller's behalf."""

    page_id: str = Field(alias="pageId")
    body_text: str = Field(alias="bodyText")
    expected_last_modified: datetime | None = Field(
        default=None, alias="dateExpectedLastModified"
    )
