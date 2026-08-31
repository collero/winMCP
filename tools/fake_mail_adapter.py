"""FakeMailAdapter — in-memory MailPort implementation used by tests.

Seeded via the constructor with per-folder lists of `MessageDetail`
(summary fields + `body`/`to`). Implements the same `MailPort` Protocol as
the real win32com-backed adapter, so tool code under test never knows the
difference — mirrors `tools/fake_task_adapter.py::FakeTaskAdapter`, which
is what lets the full Strict TDD RED-GREEN-REFACTOR cycle run on WSL2
Linux with zero `win32com` dependency (see design.md's "COM seam" /
"Mirror the calendar/tasks seam exactly" approach).

Filter sequence (per design.md's "mail_search sequence" and this change's
tasks.md): for each seeded message in the requested folder (or resolved
`folder_path`), apply in order — (1) date bounds (`date_from`/`date_to`,
either independently optional), (2) subject case-insensitive substring
match if given, (3) sender case-insensitive substring match if given,
folder-relative per design.md's "Sender filter/field asymmetry" decision:
`folder=sent` matches against the seeded message's `to` list; every other
selector (`inbox`, `drafts`, `folder_path`) matches against
`sender`/`sender_address` instead.

`drafts` and `folder_paths` were added for the mail-reading-depth change:
`drafts` is a third fixed-folder store alongside `inbox`/`sent`;
`folder_paths` is a dict of arbitrary path string -> seeded messages,
mirroring `OutlookMailAdapter`'s folder_path traversal without actually
walking anything — an unresolved key raises `MailFolderNotFoundError`,
same as an unresolved path segment would on the real adapter.
`get_message(include_html=...)` gates the seeded `html_body` the same way
the real adapter's `HTMLBody` read will (Phase 4): populated only when
`include_html=True`, `None` otherwise. `attachment_names` is always
returned as seeded — no gating.
"""
from datetime import datetime

from models.schemas import MailFolder, MessageDetail, MessageSummary
from tools.errors import MailFolderNotFoundError, MessageNotFoundError, OutlookUnavailableError


class FakeMailAdapter:
    """In-memory stand-in for `OutlookMailAdapter`, satisfying `MailPort`."""

    def __init__(
        self,
        inbox: list[MessageDetail] | None = None,
        sent: list[MessageDetail] | None = None,
        drafts: list[MessageDetail] | None = None,
        *,
        folder_paths: dict[str, list[MessageDetail]] | None = None,
        unavailable: bool = False,
    ):
        self._folders: dict[MailFolder, list[MessageDetail]] = {
            MailFolder.INBOX: list(inbox) if inbox else [],
            MailFolder.SENT: list(sent) if sent else [],
            MailFolder.DRAFTS: list(drafts) if drafts else [],
        }
        self._folder_paths: dict[str, list[MessageDetail]] = (
            {path: list(messages) for path, messages in folder_paths.items()}
            if folder_paths
            else {}
        )
        self._unavailable = unavailable

    def search(
        self,
        folder: MailFolder | None = None,
        folder_path: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        subject: str | None = None,
        sender: str | None = None,
        limit: int = 200,
    ) -> list[MessageSummary]:
        if self._unavailable:
            raise OutlookUnavailableError(
                "Outlook is not available (fake adapter configured to fail)"
            )

        if folder_path is not None:
            if folder_path not in self._folder_paths:
                raise MailFolderNotFoundError(
                    f"No folder at path {folder_path!r}",
                    path=folder_path,
                    failing_segment=folder_path,
                )
            messages = self._folder_paths[folder_path]
            is_sent = False
        else:
            folder = MailFolder(folder)
            messages = self._folders[folder]
            is_sent = folder == MailFolder.SENT

        subject_needle = subject.lower() if subject else None
        sender_needle = sender.lower() if sender else None

        matches: list[MessageSummary] = []
        for message in messages:
            if date_from is not None and message.date < date_from:
                continue
            if date_to is not None and message.date > date_to:
                continue
            if subject_needle is not None and subject_needle not in message.subject.lower():
                continue
            if sender_needle is not None and not self._matches_sender(
                message, is_sent, sender_needle
            ):
                continue
            matches.append(
                MessageSummary(
                    entry_id=message.entry_id,
                    subject=message.subject,
                    sender=message.sender,
                    sender_address=message.sender_address,
                    date=message.date,
                    has_attachments=message.has_attachments,
                )
            )
        # search-result-caps (BUG-002): mirrors OutlookMailAdapter's
        # newest-first ordering + `limit + 1` "+1 peek" bounding exactly,
        # for both the mapped-folder and folder_path paths.
        matches.sort(key=lambda summary: summary.date, reverse=True)
        return matches[: limit + 1]

    @staticmethod
    def _matches_sender(message: MessageDetail, is_sent: bool, needle: str) -> bool:
        if is_sent:
            haystack = " ".join(message.to).lower()
        else:
            haystack = f"{message.sender} {message.sender_address}".lower()
        return needle in haystack

    def get_message(self, entry_id: str, include_html: bool = False) -> MessageDetail:
        if self._unavailable:
            raise OutlookUnavailableError(
                "Outlook is not available (fake adapter configured to fail)"
            )

        for messages in (*self._folders.values(), *self._folder_paths.values()):
            for message in messages:
                if message.entry_id == entry_id:
                    if include_html:
                        return message
                    return message.model_copy(update={"html_body": None})
        raise MessageNotFoundError(f"No message with entryId {entry_id!r}")
