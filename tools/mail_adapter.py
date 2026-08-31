"""MailPort — the seam between tool logic and Outlook Inbox/Sent Items COM
access.

Defines the `MailPort` Protocol satisfied by both the real, win32com-backed
`OutlookMailAdapter` (added in a later batch) and the test-only
`FakeMailAdapter` (tools/fake_mail_adapter.py). Mirrors `CalendarPort`
(tools/outlook_adapter.py) and `TaskPort` (tools/task_adapter.py) — see
design.md's "Mirror the calendar/tasks seam exactly" approach.

A single `folder: inbox|sent` parameter on both methods drives an internal
folder->(GetDefaultFolder id, DASL date field) lookup in the real adapter
(a later batch), so one adapter/tool pair covers both folders instead of
four — see design.md's "Folder parameterization" decision.
"""
from datetime import datetime
from typing import Any, Protocol

from models.schemas import DraftDetail, MailFolder, MessageDetail, MessageSummary
from tools.errors import MailFolderNotFoundError, MessageNotFoundError, OutlookUnavailableError
from tools.settings import load_settings, local_timezone


class MailPort(Protocol):
    """Interface both the real and fake Outlook mail adapters satisfy.

    `folder_path` and `include_html` were added for the mail-reading-depth
    change (see that change's design.md's "search() signature" and
    Interfaces/Contracts sections). `folder`/`folder_path` are each
    optional at this layer — the caller (`tools/mail.py`) enforces exactly
    one via `MailSearchRequest`'s validator before invoking the adapter, so
    the invariant is not re-checked here.
    """

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
        """Return message summaries from the given folder (or `folder_path`)
        matching the given filters, newest-first, bounded to at most
        `limit + 1` rows (search-result-caps change, BUG-002's "+1 peek"
        convention — the tool layer slices to `limit` and flags
        `results_truncated` when it receives `limit + 1` rows back).
        `sender` is folder-relative — see design.md's "Sender filter/field
        asymmetry" decision: for `folder=inbox` (or `folder_path`) it
        matches the message's sender name/address; for `folder=sent` it
        matches the recipient (`to`) names/addresses instead.

        Raises MailFolderNotFoundError if `folder_path` does not resolve to
        a subfolder of the default mail store.
        """
        ...

    def get_message(self, entry_id: str, include_html: bool = False) -> MessageDetail:
        """Return full detail for the message identified by entry_id.
        `html_body` is populated only when `include_html=True` (added for
        the mail-reading-depth change); `attachment_names` is always
        populated.

        Raises MessageNotFoundError if entry_id does not resolve to an item,
        OutlookUnavailableError if Outlook cannot be reached at all.
        """
        ...

    def create_draft(
        self, to: list[str], cc: list[str], subject: str, body: str
    ) -> DraftDetail:
        """Create a new draft in Outlook's default Drafts folder and
        return its `DraftDetail` (add-mail-write-draft change). NEVER
        sends — no implementation of this port has any send capability;
        sending stays a human act in the Outlook UI. Empty `to`/`cc`
        lists are legitimate (a draft in progress).

        Raises OutlookUnavailableError if Outlook cannot be reached or
        the draft cannot be saved.
        """
        ...


# folder -> (default GetDefaultFolder id, Sort() DASL field, settings.yaml
# key, Restrict() DASL property URN), per design.md's "Folder mapping"
# table. The default ids mirror tools/outlook_adapter.py's
# _DEFAULT_CALENDAR_FOLDER_ID and tools/task_adapter.py's
# _DEFAULT_TASKS_FOLDER_ID as fallbacks — the actual folder id is resolved
# from config/settings.yaml's inbox_folder_id/sent_folder_id at COM-access
# time (config-live-folders change reverses the earlier "settings.yaml
# folder ids omitted" decision, since these keys are no longer dead once
# every real adapter reads its folder id live).
#
# The 4th element (added by the date-dasl-and-recurrence hotfix, 2026-08-26,
# BUG-004) is the quoted DASL property URN used ONLY for the `@SQL=`
# Restrict() date-range literal — never for Sort(), which keeps using the
# bracket property name (2nd element): Sort() sorts by property, no date
# string is parsed, so it carries no locale risk. `[LastModificationTime]`
# (Drafts) has no `urn:schemas:httpmail:*` equivalent, so its DASL property
# references the underlying MAPI property tag (PR_LAST_MODIFICATION_TIME,
# 0x3008, PT_SYSTIME) directly.
_FOLDER_MAP: dict[MailFolder, tuple[int, str, str, str]] = {
    MailFolder.INBOX: (
        6, "[ReceivedTime]", "inbox_folder_id", '"urn:schemas:httpmail:datereceived"',
    ),  # olFolderInbox
    MailFolder.SENT: (
        5, "[SentOn]", "sent_folder_id", '"urn:schemas:httpmail:datesent"',
    ),  # olFolderSentMail
    MailFolder.DRAFTS: (
        16, "[LastModificationTime]", "drafts_folder_id",
        '"http://schemas.microsoft.com/mapi/proptag/0x30080040"',
    ),  # olFolderDrafts
}


def _resolve_folder_id(folder: MailFolder) -> int:
    """Read the folder's settings.yaml key at COM-access time (never
    cached), falling back to `_FOLDER_MAP`'s default id when the key is
    absent or settings.yaml is unreadable."""
    default_id, _dasl_field, settings_key, _dasl_prop = _FOLDER_MAP[folder]
    try:
        settings = load_settings()
    except Exception:
        return default_id
    return int(settings.get(settings_key, default_id))


_OLMAIL_ITEM_CLASS = 43  # olMail — see design.md's "Non-MailItem guard" decision


def _is_mail_item(item: Any) -> bool:
    """True only for genuine mail items (`Class == 43`). Inbox/Sent Items
    folders can also hold meeting requests, receipts, or report items that
    lack `MailItem`-only properties — this guard must run before any other
    attribute access on `item`."""
    return getattr(item, "Class", None) == _OLMAIL_ITEM_CLASS


def _dasl_datetime(value: datetime) -> str:
    """Format a datetime for an Outlook `Items.Restrict()` DASL filter
    string literal. Mirrors `tools/outlook_adapter.py::_dasl_datetime` — an
    ISO-ordered, 24-hour literal (`yyyy-mm-dd HH:MM`) rather than a
    locale-parsed `MM/DD/YYYY hh:mm AM/PM` string (this fixes BUG-003's
    upper-bound case).

    BUG-004 (2026-08-26 live evidence) showed this ISO literal is STILL
    not safe when compared via Jet's bracket-property Restrict() syntax
    (`[ReceivedTime] >= '...'`) under es-ES: the lower bound of a range
    kept reading as day/month-transposed whenever its day was <= 12,
    silently inverting the range to an empty result. `search()` below
    therefore compares this literal via `@SQL=` DASL syntax against a
    quoted property URN instead of a bare bracket property name — DASL
    date-literal comparisons are documented as culture-invariant,
    regardless of the Outlook client's locale (design.md's "DASL @SQL=
    Restrict" decision, the date-dasl-and-recurrence hotfix)."""
    return value.strftime("%Y-%m-%d %H:%M")


def _to_aware(value: Any, tz: Any) -> datetime:
    """Attach a timezone to a naive datetime returned by Outlook COM.
    Mirrors `tools/outlook_adapter.py::_to_aware` /
    `tools/task_adapter.py::_to_aware` — already-aware values pass through
    unchanged."""
    if value.tzinfo is not None:
        return value
    return value.replace(tzinfo=tz)


def _sender_haystack(item: Any, folder: MailFolder | None) -> str:
    """Build the case-insensitive substring-match haystack for the
    `sender` filter, per design.md's "Sender filter/field asymmetry"
    decision: inbox matches the message's own sender identity; sent
    matches its recipients (`To`) instead, since Outlook does not
    populate a meaningful "sender" for items the user sent. `folder_path`
    searches pass `folder=None` here and get sender-identity matching,
    same as inbox — a `folder_path` folder is not the sent-items store."""
    if folder == MailFolder.SENT:
        return (getattr(item, "To", "") or "").lower()
    name = getattr(item, "SenderName", "") or ""
    address = getattr(item, "SenderEmailAddress", "") or ""
    return f"{name} {address}".lower()


def _resolve_date(item: Any) -> Any:
    """Pick the message's date via the fallback chain used by
    `get_message()` (all folders) and by `search()` for `drafts`/
    `folder_path` (mail-reading-depth change's "Date Resolution Fallback
    Chain" requirement): `ReceivedTime` if present, else `SentOn`, else
    `LastModificationTime`. A real Outlook MailItem retrieved by entryId
    exposes all three: Inbox items have a populated `ReceivedTime`; Sent
    Items have a populated `SentOn`; Drafts/custom-folder items may have
    neither populated, but always have `LastModificationTime`."""
    received = getattr(item, "ReceivedTime", None)
    if received:
        return received
    sent = getattr(item, "SentOn", None)
    if sent:
        return sent
    return getattr(item, "LastModificationTime", None)


def _matches_date_bounds(
    date_value: Any, date_from: datetime | None, date_to: datetime | None, tz: Any
) -> bool:
    """True if `date_value` (a raw, possibly-naive COM datetime, possibly
    `None`) falls within `[date_from, date_to]` once normalized. Used as
    the boundary re-check for every folder type (inbox/sent/drafts as
    defense-in-depth after Restrict(); `folder_path`, which skips
    Restrict() entirely, as its only date filter) — see the
    outlook-mail-adapter spec's "folder_path search skips Restrict()"
    scenario.

    datetime-tz hotfix (2026-08-26): `date_from`/`date_to` are normalized
    through the same `_to_aware` helper as `date_value` before comparing.
    `MailSearchRequest.date_from`/`date_to` (models/schemas.py) have no
    tz-aware validator, so a naive bound can reach here even though real
    Outlook COM's `ReceivedTime`/`SentOn`/etc. (`pywintypes.datetime`) are
    already timezone-aware with a fixed offset on real Windows — comparing
    the two directly raised "can't compare offset-naive and offset-aware
    datetimes" in production."""
    if date_from is None and date_to is None:
        return True
    if date_value is None:
        return False
    aware = _to_aware(date_value, tz)
    if date_from is not None and aware < _to_aware(date_from, tz):
        return False
    if date_to is not None and aware > _to_aware(date_to, tz):
        return False
    return True


def _resolve_folder_path(namespace: Any, folder_path: str) -> Any:
    """Walk `folder_path`'s `/`-delimited segments from the default mail
    store's top-level folder — never the namespace root — per design.md's
    "Path root" decision (`namespace.DefaultStore.GetRootFolder()`).
    Each segment is resolved via `current.Folders.Item(segment)`; ANY
    failure resolving a segment (missing subfolder, or a COM error
    mid-traversal) is wrapped in `MailFolderNotFoundError` naming the
    requested `path` and the specific `failing_segment`, per the
    outlook-mail-adapter spec's "Missing folder_path segment raises
    MailFolderNotFoundError" scenario."""
    current = namespace.DefaultStore.GetRootFolder()
    for segment in folder_path.split("/"):
        try:
            current = current.Folders.Item(segment)
        except Exception as exc:
            raise MailFolderNotFoundError(
                f"No folder named {segment!r} on the path to {folder_path!r}",
                path=folder_path,
                failing_segment=segment,
            ) from exc
    return current


def _split_recipients(raw_to: Any) -> list[str]:
    """Split Outlook's semicolon-delimited `To` display-name/address string
    into a list, for `MessageDetail.to`."""
    if not raw_to:
        return []
    return [part.strip() for part in raw_to.split(";") if part.strip()]


def _to_summary(item: Any, tz: Any, date_value: Any) -> MessageSummary:
    """Build a `MessageSummary` from a raw Outlook COM mail item. `sender`/
    `sender_address` always come from the item's own `SenderName`/
    `SenderEmailAddress` — Outlook populates these for Sent Items too (as
    the account owner), so no folder-relative branching is needed here
    (only the search-side sender *filter* is folder-relative)."""
    return MessageSummary(
        entry_id=item.EntryID,
        subject=item.Subject or "",
        sender=getattr(item, "SenderName", "") or "",
        sender_address=getattr(item, "SenderEmailAddress", "") or "",
        date=_to_aware(date_value, tz),
        has_attachments=item.Attachments.Count > 0,
    )


class OutlookMailAdapter:
    """Real Outlook COM-backed `MailPort` implementation.

    Connects via `win32com.client.Dispatch("Outlook.Application")` ->
    `GetNamespace("MAPI")` -> `GetDefaultFolder(id)`, per the
    outlook-mail-adapter spec's "Real Adapter COM Access Per Folder"
    requirement. `win32com.client` is imported lazily, inside
    `_dispatch_outlook`, never at module scope. Each folder's id is
    resolved from `config/settings.yaml`'s `inbox_folder_id`/
    `sent_folder_id` at COM-access time (defaults `6`/`5` when absent) —
    see the outlook-com-adapter spec's "Configurable Folder Ids"
    requirement.
    """

    def _dispatch_outlook(self) -> Any:
        """Lazily import win32com.client and connect to Outlook. Any
        failure here — missing win32com, or Outlook not installed/running —
        is mapped to OutlookUnavailableError so callers never see a raw
        ImportError or COM exception.

        Calls pythoncom.CoInitialize() on the current thread before
        Dispatch(), since COM apartments are thread-local and FastMCP
        dispatches tool calls across a worker-thread pool (outlook-com-adapter
        spec's "Per-Thread COM Initialization" requirement). CoInitialize()
        is idempotent per thread, so no CoUninitialize() pairing is used."""
        try:
            import pythoncom
            import win32com.client
        except ImportError as exc:
            raise OutlookUnavailableError(
                "win32com is not available on this platform"
            ) from exc
        try:
            pythoncom.CoInitialize()
            return win32com.client.Dispatch("Outlook.Application")
        except Exception as exc:
            raise OutlookUnavailableError(
                f"Could not connect to Outlook: {exc}"
            ) from exc

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
        outlook = self._dispatch_outlook()
        try:
            namespace = outlook.GetNamespace("MAPI")
        except Exception as exc:
            raise OutlookUnavailableError(
                f"Could not access Outlook MAPI namespace: {exc}"
            ) from exc

        resolved_folder: MailFolder | None

        if folder_path is not None:
            # folder_path search: walk the default store's tree, never
            # Restrict() (a custom folder's reliable date field is unknown
            # ahead of time — see design.md's "folderPath date filtering"
            # decision) — fetch the full Items collection and apply date
            # bounds per item in Python instead.
            try:
                target_folder = _resolve_folder_path(namespace, folder_path)
                restricted = target_folder.Items
            except MailFolderNotFoundError:
                raise
            except Exception as exc:
                raise OutlookUnavailableError(
                    f"Outlook mail search failed: {exc}"
                ) from exc
            resolved_folder = None
        else:
            resolved_folder = MailFolder(folder)
            dasl_field = _FOLDER_MAP[resolved_folder][1]
            dasl_prop = _FOLDER_MAP[resolved_folder][3]
            folder_id = _resolve_folder_id(resolved_folder)
            try:
                mail_folder = namespace.GetDefaultFolder(folder_id)
                items = mail_folder.Items
                # Newest-first at the COM source (search-result-caps
                # change, BUG-002) — lets the early-stop loop below break
                # after the first `limit + 1` matches without an unbounded
                # fetch. Sorted before Restrict(), mirroring
                # tools/outlook_adapter.py's calendar precedent. Sort()
                # takes the bracket property name — sorting by property
                # carries no date-literal-parsing risk, so it is unaffected
                # by the date-dasl-and-recurrence hotfix below (mail has no
                # IncludeRecurrences constraint forcing an ascending Sort()
                # the way calendar does).
                items.Sort(dasl_field, True)
                if date_from is not None and date_to is not None:
                    # BUG-004 hotfix: DASL `@SQL=` syntax against a quoted
                    # property URN, not Jet's bare bracket-property syntax
                    # — see `_dasl_datetime`'s docstring for the live
                    # evidence of why the bracket form is still unsafe.
                    restrict = (
                        f"@SQL={dasl_prop} >= '{_dasl_datetime(date_from)}' "
                        f"AND {dasl_prop} <= '{_dasl_datetime(date_to)}'"
                    )
                    restricted = items.Restrict(restrict)
                else:
                    restricted = items
            except Exception as exc:
                raise OutlookUnavailableError(
                    f"Outlook mail search failed: {exc}"
                ) from exc

        tz = local_timezone()
        subject_needle = subject.lower() if subject else None
        sender_needle = sender.lower() if sender else None
        # inbox/sent keep their exact pre-existing direct-field date
        # extraction (backward-compat guard); drafts and folder_path use
        # the ReceivedTime->SentOn->LastModificationTime fallback chain,
        # since their folder-appropriate timestamp may be absent.
        use_fallback_date = resolved_folder is None or resolved_folder == MailFolder.DRAFTS
        # Mapped folders (inbox/sent/drafts) are Sort()ed descending at the
        # COM source above, so the loop below can stop the moment it has
        # seen `limit + 1` post-filter matches — the "+1 peek" convention
        # (search-result-caps change) that lets the tool layer detect
        # `results_truncated` from the returned list's length alone.
        # folder_path has no such source-level ordering, so it must finish
        # the (pre-existing, unchanged-cost) full scan before it can sort
        # and bound the result in Python.
        early_stop = resolved_folder is not None

        results: list[MessageSummary] = []
        for item in restricted:
            if not _is_mail_item(item):
                continue
            if use_fallback_date:
                date_value = _resolve_date(item)
            else:
                date_field = "ReceivedTime" if resolved_folder == MailFolder.INBOX else "SentOn"
                date_value = getattr(item, date_field)
            if not _matches_date_bounds(date_value, date_from, date_to, tz):
                # For folder_path searches this is the only date filter
                # (Restrict() is always skipped there). For folder-mapped
                # searches it is a defense-in-depth boundary re-check
                # (design.md's "Python-side post-filter as
                # defense-in-depth" decision), dropping any item
                # Restrict() over-included due to a residual DASL-literal
                # locale-parsing surprise this dev host cannot verify
                # against real Outlook.
                continue
            item_subject = item.Subject or ""
            if subject_needle is not None and subject_needle not in item_subject.lower():
                continue
            if sender_needle is not None and sender_needle not in _sender_haystack(
                item, resolved_folder
            ):
                continue
            results.append(_to_summary(item, tz, date_value))
            if early_stop and len(results) > limit:
                break

        if not early_stop:
            # folder_path: no COM-level ordering — sort the full,
            # already-scanned match list by resolved date descending in
            # Python, then bound to `limit + 1` (same "+1 peek" convention
            # as the early-stop path above).
            results.sort(key=lambda message: message.date, reverse=True)
            results = results[: limit + 1]

        return results

    def create_draft(
        self, to: list[str], cc: list[str], subject: str, body: str
    ) -> DraftDetail:
        """Create and Save() a new MailItem — Outlook places a saved,
        unsent MailItem in the default Drafts folder. `Send()` is never
        called anywhere in this codebase; the draft sits in Drafts until
        a human sends it from the Outlook UI (add-mail-write-draft
        change's structural never-send guarantee)."""
        outlook = self._dispatch_outlook()
        try:
            item = outlook.CreateItem(0)  # olMailItem
            if to:
                item.To = "; ".join(to)
            if cc:
                item.CC = "; ".join(cc)
            item.Subject = subject
            item.Body = body
            item.Save()
            entry_id = item.EntryID
            saved_at = getattr(item, "LastModificationTime", None)
            if saved_at is not None:
                # Same convention as every other Outlook date read
                # (_to_aware + local_timezone): naive values get the local
                # tz attached; already-aware pywintypes values pass
                # through. See ISSUES.md ENH-005 for the open question
                # about pywintypes' UTC label on local wall-clock values.
                saved_at = _to_aware(saved_at, local_timezone())
        except Exception as exc:
            raise OutlookUnavailableError(f"Could not save draft: {exc}") from exc
        return DraftDetail(
            entry_id=entry_id,
            subject=subject,
            to=list(to),
            cc=list(cc),
            body=body,
            saved_at=saved_at,
        )

    def get_message(self, entry_id: str, include_html: bool = False) -> MessageDetail:
        outlook = self._dispatch_outlook()
        try:
            namespace = outlook.GetNamespace("MAPI")
        except Exception as exc:
            raise OutlookUnavailableError(
                f"Could not access Outlook MAPI namespace: {exc}"
            ) from exc

        try:
            item = namespace.GetItemFromID(entry_id)
        except Exception as exc:
            raise MessageNotFoundError(
                f"No message with entryId {entry_id!r}: {exc}"
            ) from exc

        if item is None or not _is_mail_item(item):
            raise MessageNotFoundError(f"No message with entryId {entry_id!r}")

        tz = local_timezone()
        summary = _to_summary(item, tz, _resolve_date(item))
        # Attachments is 1-indexed in Outlook's COM API — see the
        # outlook-mail-adapter spec's "Attachment Filename Enumeration"
        # requirement.
        attachment_names = [
            item.Attachments.Item(i).FileName
            for i in range(1, item.Attachments.Count + 1)
        ]
        # HTMLBody is read only when explicitly requested — see the
        # outlook-mail-adapter spec's "HTMLBody Read Only When Requested"
        # requirement; plain-text Body is always read regardless.
        html_body = item.HTMLBody if include_html else None
        return MessageDetail(
            entry_id=summary.entry_id,
            subject=summary.subject,
            sender=summary.sender,
            sender_address=summary.sender_address,
            date=summary.date,
            has_attachments=summary.has_attachments,
            body=item.Body or "",
            to=_split_recipients(getattr(item, "To", "")),
            attachment_names=attachment_names,
            html_body=html_body,
        )
