"""Tool-layer functions for the Outlook mail (Inbox/Sent Items) MCP tools.

Each function validates/normalizes its Pydantic request (see
`models/schemas.py`), delegates to a `MailPort` adapter (the real
win32com-backed adapter or, in tests, `FakeMailAdapter`), and lets the
adapter's typed errors (`tools/errors.py`) propagate to the caller. Mapping
those typed errors onto FastMCP's own tool-error wrapper is `server.py`'s
job — this module only needs to raise/propagate the stable
`CalendarToolError` taxonomy (plus `ValueError` for tool-input validation
failures that never reach the adapter at all).

Design note (see design.md's "Date bound handling" decision): mirrors
`tools/calendar.py`'s "at least one filter" + lookback-fill structure, but
duplicated here (not extracted to a shared helper) and backed by a NEW,
mail-specific settings key — `mail_lookback_days` (default `90` when absent
from `config/settings.yaml`) — never calendar's `lookback_days` (`7`).

mail-reading-depth: `mail_search` threads `request.folder_path` alongside
`request.folder` into the adapter call (exactly one is non-None, enforced
by `MailSearchRequest`'s validator before this function ever runs); the
mandatory-filter rule and lookback bound-fill are unchanged and apply
identically regardless of which selector was used. `mail_get_message`
threads `request.include_html_body` into the adapter's `include_html`
parameter.
"""
from datetime import datetime, timedelta, timezone

from models.schemas import (
    GetMessageRequest,
    MailSearchRequest,
    MailSearchResult,
    MessageDetail,
)
from tools.mail_adapter import MailPort
from tools.settings import load_settings, resolve_search_limit


def _mail_lookback_days() -> int:
    return int(load_settings().get("mail_lookback_days", 90))


def _normalize_search_bounds(
    date_from: datetime | None, date_to: datetime | None
) -> tuple[datetime, datetime]:
    """Fill in an omitted `dateFrom`/`dateTo` bound so the adapter always
    receives concrete datetimes, using `mail_lookback_days` as the default
    span when a bound is missing. Mirrors
    `tools/calendar.py::_normalize_search_bounds`, but reads the mail-specific
    settings key instead."""
    now = datetime.now(timezone.utc)
    lookback = timedelta(days=_mail_lookback_days())
    if date_from is None and date_to is None:
        return now - lookback, now
    if date_from is None:
        return date_to - lookback, date_to
    if date_to is None:
        return date_from, now
    return date_from, date_to


def mail_search(request: MailSearchRequest, adapter: MailPort) -> MailSearchResult:
    """Search the given Inbox/Sent Items folder, or a `folderPath`-resolved
    custom folder. Requires at least one of `dateFrom`/`dateTo`/`subject`/
    `sender`; `folder`/`folder_path` exclusivity is already enforced by
    `MailSearchRequest`'s validator before this function runs.

    `limit` (search-result-caps change, BUG-002) is resolved via
    `resolve_search_limit()` (default 50, hard max 200, `ValueError` when
    `<= 0`) before any adapter call. The adapter is expected to return up
    to `limit + 1` rows (the "+1 peek" convention) — this function slices
    to `limit` and sets `results_truncated` when the adapter's response
    exceeded it."""
    if (
        request.date_from is None
        and request.date_to is None
        and not request.subject
        and not request.sender
    ):
        raise ValueError(
            "mail_search requires at least one filter: dateFrom, dateTo, subject, or sender"
        )
    limit = resolve_search_limit(request.limit)
    date_from, date_to = _normalize_search_bounds(request.date_from, request.date_to)
    if date_from > date_to:
        # BUG-004 hotfix: an inverted range must never silently return an
        # empty result — echo both parsed bounds back to the caller.
        raise ValueError(
            f"mail_search date range is inverted: dateFrom={date_from.isoformat()} "
            f"is after dateTo={date_to.isoformat()}"
        )
    results = adapter.search(
        folder=request.folder,
        folder_path=request.folder_path,
        date_from=date_from,
        date_to=date_to,
        subject=request.subject,
        sender=request.sender,
        limit=limit,
    )
    truncated = len(results) > limit
    return MailSearchResult(results=results[:limit], results_truncated=truncated)


def mail_get_message(request: GetMessageRequest, adapter: MailPort) -> MessageDetail:
    """Fetch full detail for a single Inbox/Sent Items message by its Outlook
    entryId. `html_body` is populated only when `includeHtmlBody=true` was
    passed."""
    return adapter.get_message(request.entry_id, include_html=request.include_html_body)
