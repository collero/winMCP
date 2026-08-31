"""RED tests for tools/fake_mail_adapter.py — FakeMailAdapter (test-only
MailPort).

Covers: per-folder dispatch (inbox vs sent, seeded independently); date
bounds / subject / sender filter sequence; `sender` filter asymmetry
(inbox matches `SenderName`/`SenderEmailAddress`, sent matches `To`);
`get_message()` returns a match from either folder or raises
`MessageNotFoundError`; both methods can be configured to raise
`OutlookUnavailableError` instead (simulating COM Dispatch failure) without
ever touching real Outlook/win32com.

Also covers, for the mail-reading-depth change: a `drafts` folder store;
an arbitrary-path `folder_path` store keyed by path string (hit and
unresolved-path -> `MailFolderNotFoundError`); seeded fixtures carrying
`attachment_names`/`html_body`; `get_message(include_html=...)` gating
`html_body`.
"""
from datetime import datetime, timezone

import pytest

from models.schemas import MailFolder, MessageDetail
from tools.errors import MailFolderNotFoundError, MessageNotFoundError, OutlookUnavailableError
from tools.fake_mail_adapter import FakeMailAdapter


def _message(
    entry_id: str,
    subject: str,
    *,
    sender: str,
    sender_address: str,
    date: datetime,
    has_attachments: bool = False,
    body: str = "",
    to: list[str] | None = None,
    attachment_names: list[str] | None = None,
    html_body: str | None = None,
) -> MessageDetail:
    return MessageDetail(
        entry_id=entry_id,
        subject=subject,
        sender=sender,
        sender_address=sender_address,
        date=date,
        has_attachments=has_attachments,
        body=body,
        to=to or [],
        attachment_names=attachment_names or [],
        html_body=html_body,
    )


INBOX_MESSAGES = [
    _message(
        "MSG-1",
        "Factura agosto",
        sender="Ana Gómez",
        sender_address="ana.gomez@example.com",
        date=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
        has_attachments=True,
        body="Adjunto la factura.",
    ),
    _message(
        "MSG-2",
        "Reunion equipo",
        sender="Carlos Ruiz",
        sender_address="carlos.ruiz@example.com",
        date=datetime(2026, 8, 5, 9, 0, tzinfo=timezone.utc),
    ),
    _message(
        "MSG-3",
        "Boletin semanal",
        sender="Newsletter",
        sender_address="news@example.com",
        date=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
    ),
]

SENT_MESSAGES = [
    _message(
        "MSG-10",
        "RE: Factura agosto",
        sender="Yo",
        sender_address="yo@example.com",
        date=datetime(2026, 8, 11, 9, 0, tzinfo=timezone.utc),
        to=["ana.gomez@example.com"],
        body="Aqui tienes la respuesta.",
    ),
    _message(
        "MSG-11",
        "Envio informe",
        sender="Yo",
        sender_address="yo@example.com",
        date=datetime(2026, 8, 6, 9, 0, tzinfo=timezone.utc),
        to=["carlos.ruiz@example.com", "otro@example.com"],
    ),
]


def test_search_dispatches_to_inbox_folder():
    adapter = FakeMailAdapter(inbox=INBOX_MESSAGES, sent=SENT_MESSAGES)

    results = adapter.search(MailFolder.INBOX)

    assert {r.entry_id for r in results} == {"MSG-1", "MSG-2", "MSG-3"}


def test_search_dispatches_to_sent_folder():
    adapter = FakeMailAdapter(inbox=INBOX_MESSAGES, sent=SENT_MESSAGES)

    results = adapter.search(MailFolder.SENT)

    assert {r.entry_id for r in results} == {"MSG-10", "MSG-11"}


def test_search_filters_by_date_bounds():
    adapter = FakeMailAdapter(inbox=INBOX_MESSAGES)

    results = adapter.search(
        MailFolder.INBOX,
        date_from=datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc),
        date_to=datetime(2026, 8, 31, 23, 59, tzinfo=timezone.utc),
    )

    assert {r.entry_id for r in results} == {"MSG-1", "MSG-2"}


def test_search_narrower_upper_bound_window_is_subset_of_wider_window():
    """Superset-containment: `mail 2026-05-20..2026-06-02` must be a
    (non-empty) subset of `mail 2026-05-20..2026-06-20` — the live case
    that proved BUG-004's upper-bound defect (see
    tests/test_mail_adapter.py's `test_inbox_search_upper_bound_*` cases
    for the DASL-filter-string-level regression guard on the real
    adapter). Seeds messages between 20 May and 2 June (inside both
    windows) plus one strictly between 2 June and 20 June, so the narrow
    window's result set is a genuine proper subset, not merely equal."""
    messages = [
        _message(
            "S1", "Edge lower",
            sender="Ana Gomez", sender_address="ana.gomez@example.com",
            date=datetime(2026, 5, 20, 9, 0, tzinfo=timezone.utc),
        ),
        _message(
            "S2", "Inside narrow window",
            sender="Ana Gomez", sender_address="ana.gomez@example.com",
            date=datetime(2026, 5, 25, 9, 0, tzinfo=timezone.utc),
        ),
        _message(
            "S3", "Edge upper of narrow window",
            sender="Ana Gomez", sender_address="ana.gomez@example.com",
            date=datetime(2026, 6, 2, 9, 0, tzinfo=timezone.utc),
        ),
        _message(
            "S4", "Only inside wide window",
            sender="Ana Gomez", sender_address="ana.gomez@example.com",
            date=datetime(2026, 6, 10, 9, 0, tzinfo=timezone.utc),
        ),
        _message(
            "S5", "Edge upper of wide window",
            sender="Ana Gomez", sender_address="ana.gomez@example.com",
            date=datetime(2026, 6, 20, 9, 0, tzinfo=timezone.utc),
        ),
    ]
    adapter = FakeMailAdapter(inbox=messages)

    narrow = adapter.search(
        MailFolder.INBOX,
        date_from=datetime(2026, 5, 20, 0, 0, tzinfo=timezone.utc),
        date_to=datetime(2026, 6, 2, 23, 59, tzinfo=timezone.utc),
    )
    wide = adapter.search(
        MailFolder.INBOX,
        date_from=datetime(2026, 5, 20, 0, 0, tzinfo=timezone.utc),
        date_to=datetime(2026, 6, 20, 23, 59, tzinfo=timezone.utc),
    )

    narrow_ids = {r.entry_id for r in narrow}
    wide_ids = {r.entry_id for r in wide}

    assert narrow_ids == {"S1", "S2", "S3"}
    assert wide_ids == {"S1", "S2", "S3", "S4", "S5"}
    assert narrow_ids  # non-empty
    assert narrow_ids <= wide_ids  # narrow window's results are a subset


def test_search_filters_by_subject_case_insensitive_substring():
    adapter = FakeMailAdapter(inbox=INBOX_MESSAGES)

    results = adapter.search(MailFolder.INBOX, subject="factura")

    assert len(results) == 1
    assert results[0].entry_id == "MSG-1"


def test_search_sender_filter_matches_sender_name_on_inbox_folder():
    adapter = FakeMailAdapter(inbox=INBOX_MESSAGES)

    results = adapter.search(MailFolder.INBOX, sender="ana")

    assert len(results) == 1
    assert results[0].entry_id == "MSG-1"


def test_search_sender_filter_matches_sender_address_on_inbox_folder():
    adapter = FakeMailAdapter(inbox=INBOX_MESSAGES)

    results = adapter.search(MailFolder.INBOX, sender="carlos.ruiz@example.com")

    assert len(results) == 1
    assert results[0].entry_id == "MSG-2"


def test_search_sender_filter_matches_recipient_on_sent_folder():
    adapter = FakeMailAdapter(sent=SENT_MESSAGES)

    results = adapter.search(MailFolder.SENT, sender="ana.gomez")

    assert len(results) == 1
    assert results[0].entry_id == "MSG-10"


def test_search_result_omits_body_and_to_fields():
    adapter = FakeMailAdapter(inbox=INBOX_MESSAGES)

    results = adapter.search(MailFolder.INBOX, subject="factura")

    assert not hasattr(results[0], "body")
    assert not hasattr(results[0], "to")


def test_search_empty_result_returns_empty_list():
    adapter = FakeMailAdapter(inbox=[])

    results = adapter.search(MailFolder.INBOX, subject="Nonexistent")

    assert results == []


def test_get_message_returns_matching_detail_from_inbox():
    adapter = FakeMailAdapter(inbox=INBOX_MESSAGES, sent=SENT_MESSAGES)

    detail = adapter.get_message("MSG-1")

    assert detail.entry_id == "MSG-1"
    assert detail.subject == "Factura agosto"
    assert detail.body == "Adjunto la factura."


def test_get_message_returns_matching_detail_from_sent():
    adapter = FakeMailAdapter(inbox=INBOX_MESSAGES, sent=SENT_MESSAGES)

    detail = adapter.get_message("MSG-10")

    assert detail.entry_id == "MSG-10"
    assert detail.to == ["ana.gomez@example.com"]


def test_get_message_raises_message_not_found_for_unknown_entry_id():
    adapter = FakeMailAdapter(inbox=INBOX_MESSAGES, sent=SENT_MESSAGES)

    with pytest.raises(MessageNotFoundError):
        adapter.get_message("DOES-NOT-EXIST")


def test_search_raises_outlook_unavailable_when_configured():
    adapter = FakeMailAdapter(inbox=INBOX_MESSAGES, unavailable=True)

    with pytest.raises(OutlookUnavailableError):
        adapter.search(MailFolder.INBOX)


def test_get_message_raises_outlook_unavailable_when_configured():
    adapter = FakeMailAdapter(inbox=INBOX_MESSAGES, unavailable=True)

    with pytest.raises(OutlookUnavailableError):
        adapter.get_message("MSG-1")


# ---------------------------------------------------------------------------
# mail-reading-depth: drafts store, folder_path store, attachment_names/
# html_body seeding + include_html gating.
# ---------------------------------------------------------------------------

DRAFTS_MESSAGES = [
    _message(
        "MSG-20",
        "Borrador presupuesto",
        sender="Yo",
        sender_address="yo@example.com",
        date=datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc),
    ),
]

PROYECTOS_2026_MESSAGES = [
    _message(
        "MSG-30",
        "Kickoff proyecto",
        sender="Ana Gómez",
        sender_address="ana.gomez@example.com",
        date=datetime(2026, 8, 13, 9, 0, tzinfo=timezone.utc),
    ),
]


def test_search_dispatches_to_drafts_folder():
    adapter = FakeMailAdapter(inbox=INBOX_MESSAGES, drafts=DRAFTS_MESSAGES)

    results = adapter.search(folder=MailFolder.DRAFTS)

    assert {r.entry_id for r in results} == {"MSG-20"}


def test_search_dispatches_to_folder_path_when_path_known():
    adapter = FakeMailAdapter(
        folder_paths={"Proyectos/2026": PROYECTOS_2026_MESSAGES}
    )

    results = adapter.search(folder_path="Proyectos/2026")

    assert {r.entry_id for r in results} == {"MSG-30"}


def test_search_unknown_folder_path_raises_mail_folder_not_found_error():
    adapter = FakeMailAdapter(folder_paths={"Proyectos/2026": PROYECTOS_2026_MESSAGES})

    with pytest.raises(MailFolderNotFoundError) as excinfo:
        adapter.search(folder_path="Proyectos/NoExiste")

    assert excinfo.value.code == "mail_folder_not_found"
    assert excinfo.value.path == "Proyectos/NoExiste"
    assert excinfo.value.failing_segment == "Proyectos/NoExiste"


def test_search_folder_path_still_applies_subject_filter():
    adapter = FakeMailAdapter(folder_paths={"Proyectos/2026": PROYECTOS_2026_MESSAGES})

    results = adapter.search(folder_path="Proyectos/2026", subject="kickoff")

    assert len(results) == 1
    assert results[0].entry_id == "MSG-30"


def test_get_message_finds_message_seeded_in_drafts():
    adapter = FakeMailAdapter(drafts=DRAFTS_MESSAGES)

    detail = adapter.get_message("MSG-20")

    assert detail.entry_id == "MSG-20"
    assert detail.subject == "Borrador presupuesto"


def test_get_message_finds_message_seeded_in_folder_path():
    adapter = FakeMailAdapter(folder_paths={"Proyectos/2026": PROYECTOS_2026_MESSAGES})

    detail = adapter.get_message("MSG-30")

    assert detail.entry_id == "MSG-30"
    assert detail.subject == "Kickoff proyecto"


def test_get_message_default_omits_html_body_but_keeps_attachment_names():
    message = _message(
        "MSG-40",
        "Factura con adjunto",
        sender="Ana Gómez",
        sender_address="ana.gomez@example.com",
        date=datetime(2026, 8, 14, 9, 0, tzinfo=timezone.utc),
        has_attachments=True,
        attachment_names=["factura.pdf"],
        html_body="<p>Adjunto la factura.</p>",
    )
    adapter = FakeMailAdapter(inbox=[message])

    detail = adapter.get_message("MSG-40")

    assert detail.attachment_names == ["factura.pdf"]
    assert detail.html_body is None


def test_get_message_include_html_true_returns_seeded_html_body():
    message = _message(
        "MSG-41",
        "Factura con adjunto",
        sender="Ana Gómez",
        sender_address="ana.gomez@example.com",
        date=datetime(2026, 8, 14, 9, 0, tzinfo=timezone.utc),
        has_attachments=True,
        attachment_names=["factura.pdf"],
        html_body="<p>Adjunto la factura.</p>",
    )
    adapter = FakeMailAdapter(inbox=[message])

    detail = adapter.get_message("MSG-41", include_html=True)

    assert detail.html_body == "<p>Adjunto la factura.</p>"
    assert detail.attachment_names == ["factura.pdf"]


def test_get_message_include_html_true_but_no_seeded_html_body_stays_none():
    adapter = FakeMailAdapter(inbox=INBOX_MESSAGES)

    detail = adapter.get_message("MSG-1", include_html=True)

    assert detail.html_body is None


# ---------------------------------------------------------------------------
# search-result-caps (BUG-002): FakeMailAdapter mirrors OutlookMailAdapter's
# newest-first ordering and `limit + 1` "+1 peek" bounding exactly, for
# both the mapped-folder and folder_path paths.
# ---------------------------------------------------------------------------

_OUT_OF_ORDER_INBOX = [
    _message(
        "O-AUG10", "Reunion", sender="Ana", sender_address="ana@example.com",
        date=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
    ),
    _message(
        "O-AUG1", "Reunion", sender="Ana", sender_address="ana@example.com",
        date=datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc),
    ),
    _message(
        "O-AUG20", "Reunion", sender="Ana", sender_address="ana@example.com",
        date=datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc),
    ),
]


def test_search_returns_newest_first_for_mapped_folder():
    adapter = FakeMailAdapter(inbox=_OUT_OF_ORDER_INBOX)

    results = adapter.search(MailFolder.INBOX, subject="reunion")

    assert [r.entry_id for r in results] == ["O-AUG20", "O-AUG10", "O-AUG1"]


def test_search_bounds_to_limit_plus_one_for_mapped_folder():
    adapter = FakeMailAdapter(inbox=_OUT_OF_ORDER_INBOX)

    results = adapter.search(MailFolder.INBOX, subject="reunion", limit=1)

    assert [r.entry_id for r in results] == ["O-AUG20", "O-AUG10"]


def test_search_returns_all_when_under_limit_plus_one_for_mapped_folder():
    adapter = FakeMailAdapter(inbox=_OUT_OF_ORDER_INBOX)

    results = adapter.search(MailFolder.INBOX, subject="reunion", limit=50)

    assert [r.entry_id for r in results] == ["O-AUG20", "O-AUG10", "O-AUG1"]


def test_search_returns_newest_first_and_bounds_for_folder_path():
    adapter = FakeMailAdapter(folder_paths={"Proyectos/2026": _OUT_OF_ORDER_INBOX})

    results = adapter.search(folder_path="Proyectos/2026", subject="reunion", limit=1)

    assert [r.entry_id for r in results] == ["O-AUG20", "O-AUG10"]
