"""RED tests for tools/errors.py — typed exception taxonomy.

Each exception must exist, be raisable/catchable, and carry a stable `code`
attribute so the tool layer can map it to an MCP tool error.

Also covers `TaskNotFoundError`, added for the outlook-tasks-todo change —
it reuses the `CalendarToolError` taxonomy (see design.md's "Error taxonomy
reuse" decision) rather than introducing a new base class.

Also covers `MessageNotFoundError`, added for the outlook-mail-read change
— same reuse decision, per that change's design.md.

Also covers `SearchRootNotAllowedError`, `FileNotFoundInIndexError`, and
`WindowsSearchUnavailableError`, added for the file-search change — same
`CalendarToolError` taxonomy-reuse decision, per that change's design.md.

Also covers `PathNotFoundError`, added for the file-search-resilience
change's "Path Not Found On Disk" requirement — same taxonomy-reuse
decision, per that change's design.md.

Also covers `OneNoteUnavailableError`, `OneNotePageNotFoundError`,
`OneNoteSectionNotFoundError`, `OneNoteWriteNotAllowedError`, and
`OneNotePageConflictError`, added for the add-onenote-adapter change —
same `CalendarToolError` taxonomy-reuse decision (design.md's "Error
taxonomy" decision: one taxonomy, one `_map_error()`).
`OneNoteWriteNotAllowedError` carries `notebook_name`/`allowed_notebooks`
context, mirroring `SearchRootNotAllowedError`'s
`requested_path`/`allowed_roots` precedent.
"""
import pytest

from tools.errors import (
    AmbiguousMatchError,
    CalendarToolError,
    EventNotFoundError,
    FileNotFoundInIndexError,
    MailFolderNotFoundError,
    MessageNotFoundError,
    OneNotePageConflictError,
    OneNotePageNotFoundError,
    OneNoteSectionNotFoundError,
    OneNoteUnavailableError,
    OneNoteWriteNotAllowedError,
    OutlookUnavailableError,
    PathNotFoundError,
    SearchRootNotAllowedError,
    TaskNotFoundError,
    WindowsSearchUnavailableError,
)


def test_outlook_unavailable_error_carries_code():
    err = OutlookUnavailableError("Outlook is not running")

    assert str(err) == "Outlook is not running"
    assert err.code == "outlook_unavailable"


def test_event_not_found_error_carries_code():
    err = EventNotFoundError("No event with entryId BAD-ID")

    assert err.code == "event_not_found"


def test_ambiguous_match_error_carries_code_and_entry_ids():
    err = AmbiguousMatchError(
        "2 events match", entry_ids=["ABC123", "ABC124"]
    )

    assert err.code == "ambiguous_match"
    assert err.entry_ids == ["ABC123", "ABC124"]


def test_errors_are_raisable_and_catchable_as_exceptions():
    with pytest.raises(OutlookUnavailableError):
        raise OutlookUnavailableError("boom")

    with pytest.raises(EventNotFoundError):
        raise EventNotFoundError("boom")

    with pytest.raises(AmbiguousMatchError):
        raise AmbiguousMatchError("boom", entry_ids=["X"])


def test_task_not_found_error_carries_code():
    err = TaskNotFoundError("No task with entryId BAD-ID")

    assert str(err) == "No task with entryId BAD-ID"
    assert err.code == "task_not_found"


def test_task_not_found_error_is_a_calendar_tool_error():
    err = TaskNotFoundError("boom")

    assert isinstance(err, CalendarToolError)


def test_task_not_found_error_is_raisable_and_catchable():
    with pytest.raises(TaskNotFoundError):
        raise TaskNotFoundError("boom")


def test_message_not_found_error_carries_code():
    err = MessageNotFoundError("No message with entryId BAD-ID")

    assert str(err) == "No message with entryId BAD-ID"
    assert err.code == "message_not_found"


def test_message_not_found_error_is_a_calendar_tool_error():
    err = MessageNotFoundError("boom")

    assert isinstance(err, CalendarToolError)


def test_message_not_found_error_is_raisable_and_catchable():
    with pytest.raises(MessageNotFoundError):
        raise MessageNotFoundError("boom")


def test_mail_folder_not_found_error_carries_code_and_context():
    err = MailFolderNotFoundError(
        "No subfolder 'NoExiste' under 'Proyectos'",
        path="Proyectos/NoExiste",
        failing_segment="NoExiste",
    )

    assert str(err) == "No subfolder 'NoExiste' under 'Proyectos'"
    assert err.code == "mail_folder_not_found"
    assert err.path == "Proyectos/NoExiste"
    assert err.failing_segment == "NoExiste"


def test_mail_folder_not_found_error_is_a_calendar_tool_error():
    err = MailFolderNotFoundError("boom", path="A/B", failing_segment="B")

    assert isinstance(err, CalendarToolError)


def test_mail_folder_not_found_error_is_raisable_and_catchable():
    with pytest.raises(MailFolderNotFoundError):
        raise MailFolderNotFoundError("boom", path="A", failing_segment="A")


# ---------------------------------------------------------------------------
# file-search: SearchRootNotAllowedError, FileNotFoundInIndexError,
# WindowsSearchUnavailableError
# ---------------------------------------------------------------------------


def test_search_root_not_allowed_error_carries_code_and_context():
    err = SearchRootNotAllowedError(
        "D:\\Shared is not within an allowed root",
        requested_path="D:\\Shared",
        allowed_roots=["C:\\Users\\ana"],
    )

    assert str(err) == "D:\\Shared is not within an allowed root"
    assert err.code == "search_root_not_allowed"
    assert err.requested_path == "D:\\Shared"
    assert err.allowed_roots == ["C:\\Users\\ana"]


def test_search_root_not_allowed_error_is_a_calendar_tool_error():
    err = SearchRootNotAllowedError("boom", requested_path="X", allowed_roots=[])

    assert isinstance(err, CalendarToolError)


def test_search_root_not_allowed_error_is_raisable_and_catchable():
    with pytest.raises(SearchRootNotAllowedError):
        raise SearchRootNotAllowedError("boom", requested_path="X", allowed_roots=[])


def test_file_not_found_in_index_error_carries_code():
    err = FileNotFoundInIndexError("No indexed file at C:\\Users\\ana\\ghost.txt")

    assert str(err) == "No indexed file at C:\\Users\\ana\\ghost.txt"
    assert err.code == "file_not_found_in_index"


def test_file_not_found_in_index_error_is_a_calendar_tool_error():
    err = FileNotFoundInIndexError("boom")

    assert isinstance(err, CalendarToolError)


def test_file_not_found_in_index_error_is_raisable_and_catchable():
    with pytest.raises(FileNotFoundInIndexError):
        raise FileNotFoundInIndexError("boom")


def test_windows_search_unavailable_error_carries_code():
    err = WindowsSearchUnavailableError("Windows Search index is not reachable")

    assert str(err) == "Windows Search index is not reachable"
    assert err.code == "windows_search_unavailable"


def test_windows_search_unavailable_error_is_a_calendar_tool_error():
    err = WindowsSearchUnavailableError("boom")

    assert isinstance(err, CalendarToolError)


def test_windows_search_unavailable_error_is_raisable_and_catchable():
    with pytest.raises(WindowsSearchUnavailableError):
        raise WindowsSearchUnavailableError("boom")


# ---------------------------------------------------------------------------
# file-search-resilience: PathNotFoundError
# ---------------------------------------------------------------------------


def test_path_not_found_error_carries_code():
    err = PathNotFoundError("No file or directory at C:\\Users\\ana\\ghost.txt")

    assert str(err) == "No file or directory at C:\\Users\\ana\\ghost.txt"
    assert err.code == "path_not_found"


def test_path_not_found_error_is_a_calendar_tool_error():
    err = PathNotFoundError("boom")

    assert isinstance(err, CalendarToolError)


def test_path_not_found_error_is_raisable_and_catchable():
    with pytest.raises(PathNotFoundError):
        raise PathNotFoundError("boom")


# ---------------------------------------------------------------------------
# add-onenote-adapter: OneNoteUnavailableError, OneNotePageNotFoundError,
# OneNoteSectionNotFoundError, OneNoteWriteNotAllowedError,
# OneNotePageConflictError
# ---------------------------------------------------------------------------


def test_onenote_unavailable_error_carries_code():
    err = OneNoteUnavailableError("OneNote is not available")

    assert str(err) == "OneNote is not available"
    assert err.code == "onenote_unavailable"


def test_onenote_unavailable_error_is_a_calendar_tool_error():
    err = OneNoteUnavailableError("boom")

    assert isinstance(err, CalendarToolError)


def test_onenote_unavailable_error_is_raisable_and_catchable():
    with pytest.raises(OneNoteUnavailableError):
        raise OneNoteUnavailableError("boom")


def test_onenote_page_not_found_error_carries_code():
    err = OneNotePageNotFoundError("No page with pageId BAD-ID")

    assert str(err) == "No page with pageId BAD-ID"
    assert err.code == "onenote_page_not_found"


def test_onenote_page_not_found_error_is_a_calendar_tool_error():
    err = OneNotePageNotFoundError("boom")

    assert isinstance(err, CalendarToolError)


def test_onenote_page_not_found_error_is_raisable_and_catchable():
    with pytest.raises(OneNotePageNotFoundError):
        raise OneNotePageNotFoundError("boom")


def test_onenote_section_not_found_error_carries_code():
    err = OneNoteSectionNotFoundError("No section with sectionId BAD-ID")

    assert str(err) == "No section with sectionId BAD-ID"
    assert err.code == "onenote_section_not_found"


def test_onenote_section_not_found_error_is_a_calendar_tool_error():
    err = OneNoteSectionNotFoundError("boom")

    assert isinstance(err, CalendarToolError)


def test_onenote_section_not_found_error_is_raisable_and_catchable():
    with pytest.raises(OneNoteSectionNotFoundError):
        raise OneNoteSectionNotFoundError("boom")


def test_onenote_write_not_allowed_error_carries_code_and_context():
    err = OneNoteWriteNotAllowedError(
        "Notebook 'Informa - Proyectos' is not writable",
        notebook_name="Informa - Proyectos",
        allowed_notebooks=["z - Test Notebook"],
    )

    assert str(err) == "Notebook 'Informa - Proyectos' is not writable"
    assert err.code == "onenote_notebook_not_allowed"
    assert err.notebook_name == "Informa - Proyectos"
    assert err.allowed_notebooks == ["z - Test Notebook"]


def test_onenote_write_not_allowed_error_is_a_calendar_tool_error():
    err = OneNoteWriteNotAllowedError(
        "boom", notebook_name="X", allowed_notebooks=[]
    )

    assert isinstance(err, CalendarToolError)


def test_onenote_write_not_allowed_error_is_raisable_and_catchable():
    with pytest.raises(OneNoteWriteNotAllowedError):
        raise OneNoteWriteNotAllowedError(
            "boom", notebook_name="X", allowed_notebooks=[]
        )


def test_onenote_page_conflict_error_carries_code():
    err = OneNotePageConflictError("Page 'PAGE-1' was modified after the given date")

    assert str(err) == "Page 'PAGE-1' was modified after the given date"
    assert err.code == "onenote_page_conflict"


def test_onenote_page_conflict_error_is_a_calendar_tool_error():
    err = OneNotePageConflictError("boom")

    assert isinstance(err, CalendarToolError)


def test_onenote_page_conflict_error_is_raisable_and_catchable():
    with pytest.raises(OneNotePageConflictError):
        raise OneNotePageConflictError("boom")
