"""RED tests for models/schemas.py — Pydantic schemas for calendar tools.

Covers EventSummary/EventDetail construction, tz-aware start/end enforcement,
and EventDetail's additional `body` field.

Also covers TaskStatus/TaskSummary/TaskDetail (Outlook Tasks / Microsoft To
Do), added for the outlook-tasks-todo change.

Also covers MailFolder/MessageSummary/MessageDetail (Outlook Mail,
read-only), added for the outlook-mail-read change.

Also covers FileSearchRequest/GetFileInfoRequest/FileSummary/FileDetail
(Windows Search file lookup), added for the file-search change. Unlike
`MailSearchRequest`'s "exactly one of folder/folderPath" rule,
`FileSearchRequest` does NOT enforce "at least one of filename/phrase" at
the schema level — the file-search spec's "Both filename and phrase
omitted is rejected" scenario calls for a plain `ValueError` raised by the
tool layer (`tools/file_search.py`, a later batch), not a pydantic
`ValidationError` here.

Also covers `PageSummary`/`PageDetail`/`OneNoteSearchRequest`/
`GetPageRequest`/`CreatePageRequest`/`UpdatePageRequest` (OneNote access via
COM bridge), added for the add-onenote-adapter change. Like
`FileSearchRequest`, `OneNoteSearchRequest` does NOT enforce "query is
non-empty" or clamp `limit` at the schema level — the onenote-search
spec's "Empty query is rejected before any adapter call" and "Result Limit
Parameter" requirements call for the tool layer (`tools/onenote.py`, a
later batch) to raise a plain `ValueError`/clamp, not a pydantic
`ValidationError` here. `UpdatePageRequest.expected_last_modified` IS
required at the schema level (unlike the above) — the onenote-write-page
spec's "Update Page Requires Optimistic Concurrency" requirement is
explicit that it must never default to a value that would bypass the
concurrency check, so pydantic itself refuses to construct the request
without it.
"""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from models.schemas import (
    CalendarSearchResult,
    CreatePageRequest,
    EventDetail,
    EventSummary,
    FileDetail,
    FileSearchRequest,
    FileSearchResponse,
    FileSummary,
    GetFileInfoRequest,
    GetMessageRequest,
    GetPageRequest,
    MailFolder,
    MailSearchRequest,
    MailSearchResult,
    MessageDetail,
    MessageSummary,
    OneNoteSearchRequest,
    PageDetail,
    PageSummary,
    SearchRequest,
    TaskDetail,
    TaskSearchRequest,
    TaskSearchResult,
    TaskStatus,
    TaskSummary,
    UpdatePageRequest,
)


def test_event_summary_constructs_with_tz_aware_start_and_end():
    summary = EventSummary(
        entry_id="ABC123",
        subject="Tareas (bloque)",
        start=datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 7, 27, 10, 0, tzinfo=timezone.utc),
    )

    assert summary.entry_id == "ABC123"
    assert summary.subject == "Tareas (bloque)"
    assert summary.start.tzinfo is not None
    assert summary.end.tzinfo is not None


def test_event_summary_rejects_naive_start():
    with pytest.raises(ValidationError):
        EventSummary(
            entry_id="ABC123",
            subject="Tareas (bloque)",
            start=datetime(2026, 7, 27, 9, 0),  # naive — no tzinfo
            end=datetime(2026, 7, 27, 10, 0, tzinfo=timezone.utc),
        )


def test_event_summary_rejects_naive_end():
    with pytest.raises(ValidationError):
        EventSummary(
            entry_id="ABC123",
            subject="Tareas (bloque)",
            start=datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc),
            end=datetime(2026, 7, 27, 10, 0),  # naive — no tzinfo
        )


def test_event_detail_adds_body_field():
    detail = EventDetail(
        entry_id="ABC123",
        subject="Tareas (bloque)",
        start=datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 7, 27, 10, 0, tzinfo=timezone.utc),
        body="Politica ADN\nMarco IA Responsable",
    )

    assert detail.body == "Politica ADN\nMarco IA Responsable"
    # EventDetail IS-A EventSummary (inherits its fields)
    assert isinstance(detail, EventSummary)


def test_event_detail_allows_empty_body():
    detail = EventDetail(
        entry_id="XYZ789",
        subject="No notes",
        start=datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 7, 27, 10, 0, tzinfo=timezone.utc),
        body="",
    )

    assert detail.body == ""


def test_task_status_enum_values():
    assert TaskStatus.NOT_STARTED == "not_started"
    assert TaskStatus.IN_PROGRESS == "in_progress"
    assert TaskStatus.WAITING == "waiting"
    assert TaskStatus.DEFERRED == "deferred"
    assert TaskStatus.COMPLETED == "completed"


def test_task_summary_constructs_with_aliases():
    summary = TaskSummary(
        entryId="TASK-1",
        subject="Renovar licencia",
        dueDate=datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc),
        status=TaskStatus.IN_PROGRESS,
        isComplete=False,
    )

    assert summary.entry_id == "TASK-1"
    assert summary.subject == "Renovar licencia"
    assert summary.due_date == datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)
    assert summary.status == TaskStatus.IN_PROGRESS
    assert summary.is_complete is False


def test_task_summary_defaults_due_date_to_none_using_snake_case_names():
    summary = TaskSummary(
        entry_id="TASK-2",
        subject="Sin fecha",
        status=TaskStatus.NOT_STARTED,
        is_complete=False,
    )

    assert summary.due_date is None


def test_task_detail_adds_body_field():
    detail = TaskDetail(
        entry_id="TASK-1",
        subject="Renovar licencia",
        due_date=None,
        status=TaskStatus.COMPLETED,
        is_complete=True,
        body="Notas de la tarea",
    )

    assert detail.body == "Notas de la tarea"
    # TaskDetail IS-A TaskSummary (inherits its fields)
    assert isinstance(detail, TaskSummary)


def test_task_detail_allows_empty_body():
    detail = TaskDetail(
        entry_id="TASK-3",
        subject="No notes",
        status=TaskStatus.NOT_STARTED,
        is_complete=False,
        body="",
    )

    assert detail.body == ""


def test_mail_folder_enum_values():
    assert MailFolder.INBOX == "inbox"
    assert MailFolder.SENT == "sent"
    assert MailFolder.DRAFTS == "drafts"


def test_message_summary_constructs_with_aliases():
    summary = MessageSummary(
        entryId="MSG-1",
        subject="Factura agosto",
        sender="Ana Gómez",
        senderAddress="ana.gomez@example.com",
        date=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
        hasAttachments=True,
    )

    assert summary.entry_id == "MSG-1"
    assert summary.subject == "Factura agosto"
    assert summary.sender == "Ana Gómez"
    assert summary.sender_address == "ana.gomez@example.com"
    assert summary.date == datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)
    assert summary.has_attachments is True


def test_message_summary_constructs_with_snake_case_names():
    summary = MessageSummary(
        entry_id="MSG-2",
        subject="Sin adjuntos",
        sender="Juan Perez",
        sender_address="juan.perez@example.com",
        date=datetime(2026, 8, 11, 9, 0, tzinfo=timezone.utc),
        has_attachments=False,
    )

    assert summary.entry_id == "MSG-2"
    assert summary.has_attachments is False


def test_message_detail_adds_body_and_to_fields():
    detail = MessageDetail(
        entry_id="MSG-1",
        subject="Factura agosto",
        sender="Ana Gómez",
        sender_address="ana.gomez@example.com",
        date=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
        has_attachments=False,
        body="Adjunto la factura.",
        to=["yo@example.com"],
    )

    assert detail.body == "Adjunto la factura."
    assert detail.to == ["yo@example.com"]
    # MessageDetail IS-A MessageSummary (inherits its fields)
    assert isinstance(detail, MessageSummary)


def test_message_detail_allows_empty_body():
    detail = MessageDetail(
        entry_id="MSG-2",
        subject="Sin cuerpo",
        sender="Ana Gómez",
        sender_address="ana.gomez@example.com",
        date=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
        has_attachments=False,
        body="",
        to=[],
    )

    assert detail.body == ""


# ---------------------------------------------------------------------------
# mail-reading-depth: MailFolder.DRAFTS, folder/folderPath exclusivity,
# includeHtmlBody, attachmentNames/htmlBody.
# ---------------------------------------------------------------------------


def test_message_detail_defaults_attachment_names_empty_and_html_body_none():
    detail = MessageDetail(
        entry_id="MSG-3",
        subject="Sin adjuntos",
        sender="Ana Gómez",
        sender_address="ana.gomez@example.com",
        date=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
        has_attachments=False,
        body="",
        to=[],
    )

    assert detail.attachment_names == []
    assert detail.html_body is None


def test_message_detail_constructs_with_attachment_names_and_html_body_aliases():
    detail = MessageDetail(
        entryId="MSG-4",
        subject="Con adjuntos",
        sender="Ana Gómez",
        senderAddress="ana.gomez@example.com",
        date=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
        hasAttachments=True,
        body="Adjunto la factura.",
        to=["yo@example.com"],
        attachmentNames=["factura.pdf", "anexo.docx"],
        htmlBody="<p>Adjunto la factura.</p>",
    )

    assert detail.attachment_names == ["factura.pdf", "anexo.docx"]
    assert detail.html_body == "<p>Adjunto la factura.</p>"


def test_get_message_request_defaults_include_html_body_false():
    request = GetMessageRequest(entry_id="MSG-1")

    assert request.include_html_body is False


def test_get_message_request_accepts_include_html_body_alias():
    request = GetMessageRequest(entryId="MSG-1", includeHtmlBody=True)

    assert request.include_html_body is True


def test_mail_search_request_accepts_folder_only():
    request = MailSearchRequest(folder=MailFolder.INBOX, subject="factura")

    assert request.folder == MailFolder.INBOX
    assert request.folder_path is None


def test_mail_search_request_accepts_folder_path_only_via_alias():
    request = MailSearchRequest(folderPath="Proyectos/2026", subject="factura")

    assert request.folder is None
    assert request.folder_path == "Proyectos/2026"


def test_mail_search_request_rejects_both_folder_and_folder_path():
    with pytest.raises(ValidationError):
        MailSearchRequest(folder=MailFolder.INBOX, folderPath="Proyectos/2026", subject="x")


def test_mail_search_request_rejects_neither_folder_nor_folder_path():
    with pytest.raises(ValidationError):
        MailSearchRequest(subject="factura")


# ---------------------------------------------------------------------------
# file-search: FileSearchRequest, GetFileInfoRequest, FileSummary, FileDetail
# ---------------------------------------------------------------------------


def test_file_search_request_accepts_filename_only():
    request = FileSearchRequest(filename="report")

    assert request.filename == "report"
    assert request.phrase is None
    assert request.scope is None


def test_file_search_request_accepts_phrase_and_scope_via_snake_case():
    request = FileSearchRequest(phrase="budget forecast", scope="C:\\Users\\ana")

    assert request.phrase == "budget forecast"
    assert request.scope == "C:\\Users\\ana"


def test_file_search_request_allows_all_fields_omitted_at_schema_level():
    # The schema itself does not enforce "at least one of filename/phrase" —
    # that is a tool-layer ValueError (see file-search spec), not a
    # pydantic ValidationError. Constructing with nothing set must succeed.
    request = FileSearchRequest()

    assert request.filename is None
    assert request.phrase is None
    assert request.scope is None


def test_get_file_info_request_requires_path():
    with pytest.raises(ValidationError):
        GetFileInfoRequest()


def test_get_file_info_request_accepts_path():
    request = GetFileInfoRequest(path="C:\\Users\\ana\\Documents\\report.docx")

    assert request.path == "C:\\Users\\ana\\Documents\\report.docx"


def test_file_summary_constructs_with_aliases():
    summary = FileSummary(
        path="C:\\Users\\ana\\Documents\\report.docx",
        name="report.docx",
        size=2048,
        lastModified=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
    )

    assert summary.path == "C:\\Users\\ana\\Documents\\report.docx"
    assert summary.name == "report.docx"
    assert summary.size == 2048
    assert summary.last_modified == datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)
    assert summary.kind is None
    assert summary.extension is None


def test_file_summary_constructs_with_snake_case_names_and_optional_fields():
    summary = FileSummary(
        path="C:\\Users\\ana\\Documents\\report.docx",
        name="report.docx",
        size=2048,
        last_modified=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
        kind="Document",
        extension=".docx",
    )

    assert summary.kind == "Document"
    assert summary.extension == ".docx"


def test_file_detail_adds_created_time_and_snippet_fields():
    detail = FileDetail(
        path="C:\\Users\\ana\\Documents\\report.docx",
        name="report.docx",
        size=2048,
        last_modified=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
        created_time=datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc),
        snippet="quarterly results...",
    )

    assert detail.created_time == datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
    assert detail.snippet == "quarterly results..."
    # FileDetail IS-A FileSummary (inherits its fields)
    assert isinstance(detail, FileSummary)


# ---------------------------------------------------------------------------
# file-search-resilience: FileSearchResponse.results_truncated
# ---------------------------------------------------------------------------


def test_file_search_response_defaults_results_truncated_to_false():
    response = FileSearchResponse(results=[])

    assert response.results == []
    assert response.results_truncated is False


def test_file_search_response_accepts_results_truncated_true_via_alias():
    response = FileSearchResponse(
        results=[
            FileSummary(
                path="C:\\Users\\ana\\Documents\\report.docx",
                name="report.docx",
                size=2048,
                lastModified=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
            )
        ],
        resultsTruncated=True,
    )

    assert len(response.results) == 1
    assert response.results_truncated is True


def test_file_detail_defaults_snippet_to_none_via_created_time_alias():
    detail = FileDetail(
        path="C:\\Users\\ana\\Documents\\ghost.txt",
        name="ghost.txt",
        size=0,
        lastModified=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
        createdTime=datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc),
    )

    assert detail.snippet is None
    assert detail.created_time == datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# search-result-caps (BUG-002): `limit` on MailSearchRequest/SearchRequest/
# TaskSearchRequest, and the `_TruncatableResult`-based response envelopes
# (MailSearchResult/CalendarSearchResult/TaskSearchResult).
# ---------------------------------------------------------------------------


def test_mail_search_request_limit_defaults_to_none():
    request = MailSearchRequest(folder=MailFolder.INBOX, subject="factura")

    assert request.limit is None


def test_mail_search_request_accepts_explicit_limit():
    request = MailSearchRequest(folder=MailFolder.INBOX, subject="factura", limit=25)

    assert request.limit == 25


def test_search_request_limit_defaults_to_none():
    request = SearchRequest(subject="Tareas")

    assert request.limit is None


def test_search_request_accepts_explicit_limit():
    request = SearchRequest(subject="Tareas", limit=10)

    assert request.limit == 10


def test_task_search_request_limit_defaults_to_none():
    request = TaskSearchRequest()

    assert request.limit is None


def test_task_search_request_accepts_explicit_limit():
    request = TaskSearchRequest(limit=5)

    assert request.limit == 5


def test_mail_search_result_defaults_results_truncated_to_false():
    result = MailSearchResult(results=[])

    assert result.results == []
    assert result.results_truncated is False


def test_mail_search_result_accepts_results_truncated_true_via_alias():
    message = MessageSummary(
        entryId="MSG-1",
        subject="Factura agosto",
        sender="Ana Gómez",
        senderAddress="ana.gomez@example.com",
        date=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
        hasAttachments=False,
    )

    result = MailSearchResult(results=[message], resultsTruncated=True)

    assert len(result.results) == 1
    assert result.results_truncated is True


def test_calendar_search_result_defaults_results_truncated_to_false():
    result = CalendarSearchResult(results=[])

    assert result.results == []
    assert result.results_truncated is False


def test_calendar_search_result_accepts_results_truncated_true_via_alias():
    event = EventSummary(
        entry_id="ABC123",
        subject="Tareas (bloque)",
        start=datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 7, 27, 10, 0, tzinfo=timezone.utc),
    )

    result = CalendarSearchResult(results=[event], resultsTruncated=True)

    assert len(result.results) == 1
    assert result.results_truncated is True


def test_task_search_result_defaults_results_truncated_to_false():
    result = TaskSearchResult(results=[])

    assert result.results == []
    assert result.results_truncated is False


def test_task_search_result_accepts_results_truncated_true_via_alias():
    task = TaskSummary(
        entryId="TASK-1",
        subject="Renovar licencia",
        status=TaskStatus.IN_PROGRESS,
        isComplete=False,
    )

    result = TaskSearchResult(results=[task], resultsTruncated=True)

    assert len(result.results) == 1
    assert result.results_truncated is True


# ---------------------------------------------------------------------------
# add-onenote-adapter: PageSummary, PageDetail, OneNoteSearchRequest,
# GetPageRequest, CreatePageRequest, UpdatePageRequest
# ---------------------------------------------------------------------------


def test_page_summary_constructs_via_aliases():
    summary = PageSummary(
        pageId="PAGE-1",
        title="Reunión semanal",
        notebookName="z - Test Notebook",
        sectionName="Notas",
        lastModifiedDateTime=datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc),
    )

    assert summary.page_id == "PAGE-1"
    assert summary.title == "Reunión semanal"
    assert summary.notebook_name == "z - Test Notebook"
    assert summary.section_name == "Notas"
    assert summary.last_modified == datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)


def test_page_summary_last_modified_defaults_to_none_when_omitted():
    summary = PageSummary(
        pageId="PAGE-2",
        title="Sin fecha",
        notebookName="z - Test Notebook",
        sectionName="Notas",
    )

    assert summary.last_modified is None


def test_page_detail_adds_body_text_field():
    detail = PageDetail(
        pageId="PAGE-1",
        title="Reunión semanal",
        notebookName="z - Test Notebook",
        sectionName="Notas",
        bodyText="Notas de la reunión.",
    )

    assert detail.body_text == "Notas de la reunión."
    # PageDetail IS-A PageSummary (inherits its fields)
    assert isinstance(detail, PageSummary)


def test_page_detail_allows_empty_body_text():
    detail = PageDetail(
        pageId="PAGE-2",
        title="Sin cuerpo",
        notebookName="z - Test Notebook",
        sectionName="Notas",
        bodyText="",
    )

    assert detail.body_text == ""


def test_onenote_search_request_constructs_with_query_only():
    request = OneNoteSearchRequest(query="factura")

    assert request.query == "factura"
    assert request.limit is None


def test_onenote_search_request_accepts_limit():
    request = OneNoteSearchRequest(query="factura", limit=10000)

    # No clamping/validation at the schema level — the tool layer resolves
    # this (onenote-search spec's "Result Limit Parameter" requirement).
    assert request.limit == 10000


def test_get_page_request_constructs_via_alias():
    request = GetPageRequest(pageId="PAGE-1")

    assert request.page_id == "PAGE-1"


def test_create_page_request_constructs_via_aliases():
    request = CreatePageRequest(
        sectionId="SECTION-1", title="Nueva página", bodyText="Cuerpo de la página."
    )

    assert request.section_id == "SECTION-1"
    assert request.title == "Nueva página"
    assert request.body_text == "Cuerpo de la página."


def test_update_page_request_constructs_via_aliases():
    request = UpdatePageRequest(
        pageId="PAGE-1",
        bodyText="Cuerpo actualizado.",
        dateExpectedLastModified=datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc),
    )

    assert request.page_id == "PAGE-1"
    assert request.body_text == "Cuerpo actualizado."
    assert request.expected_last_modified == datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)


def test_update_page_request_expected_last_modified_is_optional():
    """Changed 2026-08-28 (onenote/0005 mailbox round): an OMITTED
    `dateExpectedLastModified` is the documented unguarded-overwrite
    escape hatch — OneNote's two per-page timestamps diverge after a
    write settles, so a caller whose freshly-read value is still refused
    needs a way through. A SUPPLIED value is still passed through
    unchanged, never replaced by one that would bypass the check."""
    request = UpdatePageRequest(pageId="PAGE-1", bodyText="Cuerpo actualizado.")

    assert request.expected_last_modified is None


# --- BUG-006 round 3 (file_write/0073): the PowerShell bridge's phrase leg
# delivers UTC-NAIVE datetimes (live-verified against os.stat, DST-proof
# across April/October files), which serialize without an offset and fail
# the MCP output schema's RFC 3339 date-time format — every row rejected
# AT the boundary. FileSummary/FileDetail coerce naive datetimes to
# UTC-aware so every route serializes with an offset.
from models.schemas import FileDetail, FileSummary


def test_file_summary_naive_last_modified_coerced_to_utc():
    row = FileSummary(
        path="C:\\co\\f.txt",
        name="f.txt",
        size=1,
        last_modified=datetime(2026, 8, 31, 10, 48, 49),  # naive — live bridge shape
    )

    assert row.last_modified.tzinfo is not None
    assert row.last_modified.utcoffset().total_seconds() == 0
    serialized = row.model_dump_json(by_alias=True)
    assert '"lastModified":"2026-08-31T10:48:49Z"' in serialized or (
        '"lastModified":"2026-08-31T10:48:49+00:00"' in serialized
    )


def test_file_summary_aware_last_modified_passes_through_unchanged():
    aware = datetime(2026, 6, 2, 16, 2, 15, 997588, tzinfo=timezone.utc)
    row = FileSummary(path="C:\\co\\f.txt", name="f.txt", size=1, last_modified=aware)

    assert row.last_modified == aware


def test_file_detail_naive_created_time_coerced_to_utc():
    detail = FileDetail(
        path="C:\\co\\f.txt",
        name="f.txt",
        size=1,
        last_modified=datetime(2026, 8, 31, 10, 48, 49),
        created_time=datetime(2026, 8, 30, 9, 0, 0),
    )

    assert detail.created_time.utcoffset().total_seconds() == 0
