"""Tests for tools/mail.py — the tool-layer functions for the two Outlook
mail MCP tools (mail_search, mail_get_message), exercised against
FakeMailAdapter.

Phase 3: mail_search (mail-search spec)
Phase 4: mail_get_message (mail-get-detail spec)
"""
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from models.schemas import GetMessageRequest, MailFolder, MailSearchRequest, MessageDetail
from tools.errors import MailFolderNotFoundError, MessageNotFoundError, OutlookUnavailableError
from tools.fake_mail_adapter import FakeMailAdapter
from tools.mail import mail_get_message, mail_search


def _message(
    entry_id: str,
    subject: str,
    *,
    sender: str = "Ana Gómez",
    sender_address: str = "ana.gomez@example.com",
    date: datetime = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
    has_attachments: bool = False,
    to: list[str] | None = None,
    body: str = "",
) -> MessageDetail:
    return MessageDetail(
        entry_id=entry_id,
        subject=subject,
        sender=sender,
        sender_address=sender_address,
        date=date,
        has_attachments=has_attachments,
        to=to if to is not None else ["yo@example.com"],
        body=body,
    )


# ---------------------------------------------------------------------------
# Phase 3: mail_search
# ---------------------------------------------------------------------------


def test_search_valid_folder_and_date_range(mocker):
    messages = [
        _message("MSG-1", "Factura agosto", date=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)),
        _message("MSG-2", "Otra cosa", date=datetime(2026, 8, 10, 10, 0, tzinfo=timezone.utc)),
        _message("MSG-3", "Mas cosas", date=datetime(2026, 8, 10, 11, 0, tzinfo=timezone.utc)),
    ]
    adapter = FakeMailAdapter(inbox=messages)
    spy = mocker.spy(adapter, "search")

    date_from = datetime(2026, 8, 10, 0, 0, tzinfo=timezone.utc)
    date_to = datetime(2026, 8, 10, 23, 59, 59, tzinfo=timezone.utc)
    request = MailSearchRequest(folder=MailFolder.INBOX, date_from=date_from, date_to=date_to)

    result = mail_search(request, adapter)

    # mail-reading-depth: adapter.search() gained a folder_path parameter
    # between folder and date_from (see tools/mail_adapter.py::MailPort),
    # so tools/mail.py now calls it with keywords instead of positionally
    # — this assertion was updated from a positional
    # `assert_called_once_with(MailFolder.INBOX, date_from, date_to, ...)`
    # to keyword form to match, per this change's design.md.
    # search-result-caps: `limit` is now also threaded through, resolved
    # via `resolve_search_limit(None)` -> the default 50 (unconfigured
    # `search_default_limit` in the real config/settings.yaml).
    spy.assert_called_once_with(
        folder=MailFolder.INBOX,
        folder_path=None,
        date_from=date_from,
        date_to=date_to,
        subject=None,
        sender=None,
        limit=50,
    )
    assert len(result.results) == 3
    assert result.results_truncated is False


def test_search_all_filters_omitted_raises_value_error():
    adapter = FakeMailAdapter(inbox=[])
    spy_search = None
    request = MailSearchRequest(folder=MailFolder.INBOX)

    with pytest.raises(ValueError, match="filter"):
        mail_search(request, adapter)


def test_search_missing_folder_rejected():
    with pytest.raises(ValidationError):
        MailSearchRequest(subject="Factura")


def test_search_subject_only_fills_both_bounds_from_mail_lookback_days_default_90(mocker):
    """Triangulation: subject-only request (dateFrom/dateTo both omitted)
    must still reach the adapter with concrete, normalized datetimes,
    defaulting to 90 days when `mail_lookback_days` is absent from
    settings — NOT calendar's 7-day `lookback_days`."""
    mocker.patch("tools.mail.load_settings", return_value={})
    messages = [_message("MSG-1", "Factura agosto")]
    adapter = FakeMailAdapter(inbox=messages)
    spy = mocker.spy(adapter, "search")
    request = MailSearchRequest(folder=MailFolder.INBOX, subject="factura")

    mail_search(request, adapter)

    spy.assert_called_once()
    # mail-reading-depth: tools/mail.py now calls adapter.search() with
    # keywords (see the folder_path insertion note above) — read via
    # .kwargs instead of unpacking .args.
    kwargs = spy.call_args.kwargs
    assert kwargs["folder"] == MailFolder.INBOX
    assert kwargs["date_from"].tzinfo is not None
    assert kwargs["date_to"].tzinfo is not None
    assert kwargs["date_from"] < kwargs["date_to"]
    assert kwargs["date_to"] - kwargs["date_from"] == timedelta(days=90)


def test_search_sender_only_uses_configured_mail_lookback_days_30_not_calendar_lookback_days(
    mocker,
):
    mocker.patch("tools.mail.load_settings", return_value={"mail_lookback_days": 30})
    adapter = FakeMailAdapter(sent=[_message("MSG-1", "Hola", to=["ana.gomez@example.com"])])
    spy = mocker.spy(adapter, "search")
    request = MailSearchRequest(folder=MailFolder.SENT, sender="ana")

    mail_search(request, adapter)

    spy.assert_called_once()
    kwargs = spy.call_args.kwargs
    assert kwargs["folder"] == MailFolder.SENT
    assert kwargs["date_to"] - kwargs["date_from"] == timedelta(days=30)
    assert kwargs["date_to"] - kwargs["date_from"] != timedelta(days=7)


def test_search_only_date_from_given_fills_date_to_with_now(mocker):
    mocker.patch("tools.mail.load_settings", return_value={})
    adapter = FakeMailAdapter(inbox=[_message("MSG-1", "Factura agosto")])
    spy = mocker.spy(adapter, "search")
    date_from = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
    request = MailSearchRequest(folder=MailFolder.INBOX, subject="factura", date_from=date_from)

    mail_search(request, adapter)

    spy.assert_called_once()
    kwargs = spy.call_args.kwargs
    assert kwargs["date_from"] == date_from
    now = datetime.now(timezone.utc)
    assert abs((now - kwargs["date_to"]).total_seconds()) < 5


def test_search_sender_filter_matches_recipient_on_sent_folder():
    adapter = FakeMailAdapter(
        sent=[_message("MSG-1", "Hola", to=["ana.gomez@example.com"])]
    )
    request = MailSearchRequest(folder=MailFolder.SENT, sender="ana.gomez")

    result = mail_search(request, adapter)

    assert len(result.results) == 1
    assert result.results[0].entry_id == "MSG-1"


def test_search_sender_filter_matches_sender_name_on_inbox_folder():
    adapter = FakeMailAdapter(
        inbox=[_message("MSG-1", "Hola", sender="Ana Gómez", sender_address="ana@example.com")]
    )
    request = MailSearchRequest(folder=MailFolder.INBOX, sender="ana")

    result = mail_search(request, adapter)

    assert len(result.results) == 1
    assert result.results[0].entry_id == "MSG-1"


def test_search_empty_result_returns_empty_list():
    adapter = FakeMailAdapter(inbox=[])
    request = MailSearchRequest(folder=MailFolder.INBOX, subject="Nonexistent")

    result = mail_search(request, adapter)

    assert result.results == []
    assert result.results_truncated is False


def test_search_outlook_unavailable_returns_tool_error():
    adapter = FakeMailAdapter(inbox=[], unavailable=True)
    request = MailSearchRequest(folder=MailFolder.INBOX, subject="Factura")

    with pytest.raises(OutlookUnavailableError):
        mail_search(request, adapter)


# ---------------------------------------------------------------------------
# mail-reading-depth: folder_path threading, mandatory-filter rule applies
# identically to folderPath, and backward-compat guards for folder=inbox/
# sent and default (no includeHtmlBody) get_message behavior.
# ---------------------------------------------------------------------------


def test_search_folder_path_passed_through_to_adapter(mocker):
    messages = [_message("MSG-30", "Kickoff proyecto")]
    adapter = FakeMailAdapter(folder_paths={"Proyectos/2026": messages})
    spy = mocker.spy(adapter, "search")
    request = MailSearchRequest(folderPath="Proyectos/2026", subject="kickoff")

    result = mail_search(request, adapter)

    kwargs = spy.call_args.kwargs
    assert kwargs["folder"] is None
    assert kwargs["folder_path"] == "Proyectos/2026"
    assert len(result.results) == 1
    assert result.results[0].entry_id == "MSG-30"


def test_search_folder_path_unresolved_raises_mail_folder_not_found_error():
    adapter = FakeMailAdapter(folder_paths={"Proyectos/2026": []})
    request = MailSearchRequest(folderPath="Proyectos/NoExiste", subject="x")

    with pytest.raises(MailFolderNotFoundError):
        mail_search(request, adapter)


def test_search_mandatory_filter_rule_applies_to_folder_path_too():
    adapter = FakeMailAdapter(folder_paths={"Proyectos/2026": []})
    request = MailSearchRequest(folderPath="Proyectos/2026")

    with pytest.raises(ValueError, match="filter"):
        mail_search(request, adapter)


def test_search_folder_inbox_and_sent_backward_compatible(mocker):
    """No-regression guard: folder=inbox/sent calls still validate, call
    the adapter, and return results the same way they did before
    folder_path/includeHtmlBody were added."""
    inbox_messages = [_message("MSG-1", "Factura agosto")]
    sent_messages = [_message("MSG-10", "Hola", to=["ana.gomez@example.com"])]
    adapter = FakeMailAdapter(inbox=inbox_messages, sent=sent_messages)
    spy = mocker.spy(adapter, "search")

    inbox_request = MailSearchRequest(folder=MailFolder.INBOX, subject="factura")
    inbox_result = mail_search(inbox_request, adapter)
    assert len(inbox_result.results) == 1
    assert inbox_result.results[0].entry_id == "MSG-1"
    assert spy.call_args.kwargs["folder"] == MailFolder.INBOX
    assert spy.call_args.kwargs["folder_path"] is None

    sent_request = MailSearchRequest(folder=MailFolder.SENT, sender="ana.gomez")
    sent_result = mail_search(sent_request, adapter)
    assert len(sent_result.results) == 1
    assert sent_result.results[0].entry_id == "MSG-10"
    assert spy.call_args.kwargs["folder"] == MailFolder.SENT
    assert spy.call_args.kwargs["folder_path"] is None


# ---------------------------------------------------------------------------
# Phase 4: mail_get_message
# ---------------------------------------------------------------------------


def test_get_message_success_returns_full_detail():
    detail = _message(
        "MSG-1",
        "Factura agosto",
        sender="Ana Gómez",
        sender_address="ana.gomez@example.com",
        to=["yo@example.com"],
        body="Adjunto la factura.",
    )
    adapter = FakeMailAdapter(inbox=[detail])
    request = GetMessageRequest(entry_id="MSG-1")

    result = mail_get_message(request, adapter)

    assert result.entry_id == "MSG-1"
    assert result.subject == "Factura agosto"
    assert result.sender == "Ana Gómez"
    assert result.sender_address == "ana.gomez@example.com"
    assert result.to == ["yo@example.com"]
    assert result.body == "Adjunto la factura."


def test_get_message_not_found_raises_tool_error():
    adapter = FakeMailAdapter(inbox=[])
    request = GetMessageRequest(entry_id="BAD-ID")

    with pytest.raises(MessageNotFoundError):
        mail_get_message(request, adapter)


def test_get_message_empty_body_returns_empty_string():
    detail = _message("MSG-2", "No notes", body="")
    adapter = FakeMailAdapter(inbox=[detail])
    request = GetMessageRequest(entry_id="MSG-2")

    result = mail_get_message(request, adapter)

    assert result.body == ""
    assert result.subject == "No notes"


def test_get_message_outlook_unavailable_returns_tool_error():
    adapter = FakeMailAdapter(inbox=[], unavailable=True)
    request = GetMessageRequest(entry_id="MSG-1")

    with pytest.raises(OutlookUnavailableError):
        mail_get_message(request, adapter)


def test_get_message_include_html_body_threaded_to_adapter(mocker):
    detail = _message(
        "MSG-41",
        "Factura con adjunto",
        body="Adjunto la factura.",
    )
    # Seed html_body directly since _message()'s helper doesn't expose it.
    detail = detail.model_copy(update={"html_body": "<p>Adjunto la factura.</p>"})
    adapter = FakeMailAdapter(inbox=[detail])
    spy = mocker.spy(adapter, "get_message")
    request = GetMessageRequest(entryId="MSG-41", includeHtmlBody=True)

    result = mail_get_message(request, adapter)

    spy.assert_called_once_with("MSG-41", include_html=True)
    assert result.html_body == "<p>Adjunto la factura.</p>"
    assert result.body == "Adjunto la factura."


def test_get_message_default_omits_html_body_backward_compatible(mocker):
    """No-regression guard: a request with includeHtmlBody omitted still
    calls the adapter and returns the same shape as before — html_body
    stays None/omitted."""
    detail = _message("MSG-1", "Factura agosto", body="Adjunto la factura.")
    adapter = FakeMailAdapter(inbox=[detail])
    spy = mocker.spy(adapter, "get_message")
    request = GetMessageRequest(entry_id="MSG-1")

    result = mail_get_message(request, adapter)

    spy.assert_called_once_with("MSG-1", include_html=False)
    assert result.html_body is None
    assert result.body == "Adjunto la factura."


# ---------------------------------------------------------------------------
# Phase 7: config/settings.yaml's mail_lookback_days is a LIVE key - this
# test exercises the real, unmocked config/settings.yaml file (via
# _mail_lookback_days(), not a mocked load_settings()), closing the gap
# flagged in Batch 2's apply-progress: "Phase 7 hasn't added the key yet"
# no longer applies. (calendar_folder_id/tasks_folder_id were dead at the
# time this comment was first written; the config-live-folders change made
# every settings.yaml key live — see tests/test_outlook_adapter.py,
# tests/test_task_adapter.py, tests/test_mail_adapter.py for their own
# literal-key tests.)
# ---------------------------------------------------------------------------


def test_search_default_limit_50_bounds_and_flags_oversized_result(mocker):
    """search-result-caps (BUG-002): omitting `limit` resolves to the
    default 50, and when the true match count exceeds it, the response is
    bounded to 50 rows and `results_truncated` is `true` — spec's
    "Oversized subject search is bounded and flagged" scenario."""
    mocker.patch("tools.settings.load_settings", return_value={})
    messages = [
        _message(f"MSG-{i}", "a", date=datetime(2026, 8, 1, tzinfo=timezone.utc) + timedelta(hours=i))
        for i in range(1000)
    ]
    adapter = FakeMailAdapter(inbox=messages)
    request = MailSearchRequest(folder=MailFolder.INBOX, subject="a")

    result = mail_search(request, adapter)

    assert len(result.results) == 50
    assert result.results_truncated is True


def test_search_limit_above_hard_max_clamped_to_200_not_rejected(mocker):
    mocker.patch("tools.settings.load_settings", return_value={})
    messages = [
        _message(f"MSG-{i}", "a", date=datetime(2026, 8, 1, tzinfo=timezone.utc) + timedelta(hours=i))
        for i in range(500)
    ]
    adapter = FakeMailAdapter(inbox=messages)
    spy = mocker.spy(adapter, "search")
    request = MailSearchRequest(folder=MailFolder.INBOX, subject="a", limit=10000)

    result = mail_search(request, adapter)

    assert spy.call_args.kwargs["limit"] == 200
    assert len(result.results) == 200
    assert result.results_truncated is True


def test_search_non_positive_limit_rejected_before_adapter_call(mocker):
    adapter = FakeMailAdapter(inbox=[])
    spy = mocker.spy(adapter, "search")
    request = MailSearchRequest(folder=MailFolder.INBOX, subject="a", limit=0)

    with pytest.raises(ValueError):
        mail_search(request, adapter)

    spy.assert_not_called()


def test_search_out_of_order_source_items_returned_newest_first():
    """spec's "Out-of-order source items are returned newest-first"
    scenario, exercised at the mail_search tool boundary (not just the
    adapter/fake-adapter layers)."""
    messages = [
        _message("M-AUG10", "reunion", date=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)),
        _message("M-AUG1", "reunion", date=datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)),
        _message("M-AUG20", "reunion", date=datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)),
    ]
    adapter = FakeMailAdapter(inbox=messages)
    request = MailSearchRequest(folder=MailFolder.INBOX, subject="reunion")

    result = mail_search(request, adapter)

    assert [m.entry_id for m in result.results] == ["M-AUG20", "M-AUG10", "M-AUG1"]


def test_search_under_cap_result_not_marked_truncated():
    messages = [_message(f"MSG-{i}", "factura") for i in range(10)]
    adapter = FakeMailAdapter(inbox=messages)
    request = MailSearchRequest(folder=MailFolder.INBOX, subject="factura", limit=50)

    result = mail_search(request, adapter)

    assert len(result.results) == 10
    assert result.results_truncated is False


def test_search_inverted_range_raises_value_error_echoing_both_bounds():
    """BUG-004 hotfix: an inverted explicit range must raise, never
    silently return an empty result."""
    adapter = FakeMailAdapter(inbox=[])
    request = MailSearchRequest(
        folder=MailFolder.INBOX,
        date_from=datetime(2026, 6, 10, 0, 0, tzinfo=timezone.utc),
        date_to=datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc),
    )

    with pytest.raises(ValueError, match="inverted") as exc_info:
        mail_search(request, adapter)

    assert "2026-06-10" in str(exc_info.value)
    assert "2026-06-01" in str(exc_info.value)


def test_search_wider_range_is_superset_of_narrower_contained_range():
    """Superset-containment regression (BUG-004's recommended property
    test): any range's results must be a superset of every sub-range it
    contains."""
    messages = [
        _message(f"MSG-{day:02d}", "factura", date=datetime(2026, 1, day, 9, 0, tzinfo=timezone.utc))
        for day in range(1, 29)
    ]
    adapter = FakeMailAdapter(inbox=messages)

    wide_request = MailSearchRequest(
        folder=MailFolder.INBOX,
        date_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        date_to=datetime(2026, 1, 28, 23, 59, 59, tzinfo=timezone.utc),
        subject="factura",
        limit=200,
    )
    narrow_request = MailSearchRequest(
        folder=MailFolder.INBOX,
        date_from=datetime(2026, 1, 8, tzinfo=timezone.utc),
        date_to=datetime(2026, 1, 19, 23, 59, 59, tzinfo=timezone.utc),
        subject="factura",
        limit=200,
    )

    wide_ids = {m.entry_id for m in mail_search(wide_request, adapter).results}
    narrow_ids = {m.entry_id for m in mail_search(narrow_request, adapter).results}

    assert narrow_ids <= wide_ids
    assert narrow_ids == {f"MSG-{day:02d}" for day in range(8, 20)}


def test_settings_yaml_declares_mail_lookback_days_90():
    """Asserts the literal key is present in config/settings.yaml (not just
    that the code's default happens to also be 90 when the key is absent -
    that would pass trivially before Phase 7 adds the key at all)."""
    from tools.settings import load_settings

    settings = load_settings()

    assert "mail_lookback_days" in settings
    assert settings["mail_lookback_days"] == 90


# --- mail_write_draft (add-mail-write-draft change) ---
# Creates a draft in Outlook's Drafts folder for HUMAN review — the tool
# (and the whole server) has no send capability; that is the safety model,
# structural rather than policed.


def test_write_draft_creates_draft_via_adapter():
    from models.schemas import WriteDraftRequest
    from tools.mail import mail_write_draft

    adapter = FakeMailAdapter()
    request = WriteDraftRequest(
        to=["ana.gomez@example.com"],
        cc=["luis@example.com"],
        subject="Acta de la reunión",
        body="Adjunto el acta.",
    )

    draft = mail_write_draft(request, adapter)

    assert draft.entry_id
    assert draft.subject == "Acta de la reunión"
    assert draft.to == ["ana.gomez@example.com"]
    assert draft.cc == ["luis@example.com"]
    assert draft.folder == "drafts"


def test_write_draft_allows_empty_recipients_for_a_working_draft():
    """A draft with a body but no recipients yet is a legitimate draft —
    the human adds recipients in Outlook before sending."""
    from models.schemas import WriteDraftRequest
    from tools.mail import mail_write_draft

    adapter = FakeMailAdapter()

    draft = mail_write_draft(
        WriteDraftRequest(subject="Notas", body="Texto."), adapter
    )

    assert draft.to == []


def test_write_draft_completely_empty_request_rejected_before_adapter(mocker):
    from models.schemas import WriteDraftRequest
    from tools.mail import mail_write_draft

    adapter = FakeMailAdapter()
    spy = mocker.spy(adapter, "create_draft")

    with pytest.raises(ValueError):
        mail_write_draft(WriteDraftRequest(), adapter)

    spy.assert_not_called()


def test_write_draft_blank_recipient_rejected_before_adapter(mocker):
    """An empty-string recipient would silently produce '; ' runs in the
    Outlook To line — rejected as invalid input, never passed through."""
    from models.schemas import WriteDraftRequest
    from tools.mail import mail_write_draft

    adapter = FakeMailAdapter()
    spy = mocker.spy(adapter, "create_draft")

    with pytest.raises(ValueError):
        mail_write_draft(
            WriteDraftRequest(to=["ana@example.com", "  "], subject="s"), adapter
        )

    spy.assert_not_called()


def test_write_draft_unavailable_raises_tool_error():
    from models.schemas import WriteDraftRequest
    from tools.mail import mail_write_draft

    adapter = FakeMailAdapter(unavailable=True)

    with pytest.raises(OutlookUnavailableError):
        mail_write_draft(WriteDraftRequest(subject="s", body="b"), adapter)
