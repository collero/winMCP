"""Tool-layer functions for the Outlook calendar MCP tools.

Each function validates/normalizes its Pydantic request (see
`models/schemas.py`), delegates to a `CalendarPort` adapter (the real
win32com-backed adapter or, in tests, `FakeCalendarAdapter`), and lets the
adapter's typed errors (`tools/errors.py`) propagate to the caller. Mapping
those typed errors onto FastMCP's own tool-error wrapper is `server.py`'s
job (Phase 8) — this module only needs to raise/propagate the stable
`CalendarToolError` taxonomy (plus `ValueError` for tool-input validation
failures that never reach the adapter at all).

Design note (see design.md's "Datetime handling" decision and Phase 3's
apply-progress handoff): `CalendarPort.search()` requires concrete
(non-optional) `date_from`/`date_to` datetimes, but the MCP-facing
`SearchRequest` allows both to be omitted (as long as `subject` is given).
`_normalize_search_bounds` fills in any omitted bound using
`config/settings.yaml`'s `lookback_days` before calling the adapter.
"""
from datetime import datetime, time, timedelta, timezone

from models.schemas import (
    CalendarSearchResult,
    EventDetail,
    GetEventRequest,
    GetNotesRequest,
    SearchRequest,
    SearchWindow,
)
from tools.errors import AmbiguousMatchError, EventNotFoundError
from tools.outlook_adapter import CalendarPort
from tools.settings import (
    calendar_subject_search_lookahead_days,
    calendar_subject_search_lookback_days,
    load_settings,
    local_timezone,
    resolve_search_limit,
)


def _now() -> datetime:
    """Seam for tests to freeze "now" via `mocker.patch("tools.calendar._now",
    return_value=...)` instead of relying on wall-clock timing."""
    return datetime.now(timezone.utc)


def _lookback_days() -> int:
    return int(load_settings().get("lookback_days", 7))


def _subject_search_window() -> tuple[datetime, datetime]:
    """The default window a subject-only `calendar_search` request (no
    explicit `from`/`to`) auto-applies (BUG-008 hotfix, 2026-08-26):
    symmetric and forward-leaning (default 90 days back, 365 days
    forward — `calendar_subject_search_lookback_days`/`..._lookahead_days`)
    rather than the plain backward-only `lookback_days` default used to
    fill a *partially* explicit range. A calendar's value is mostly ahead
    of today, and a backward-only window can never answer "when is my
    next X?" — the most common calendar question there is."""
    now = _now()
    lookback = timedelta(days=calendar_subject_search_lookback_days())
    lookahead = timedelta(days=calendar_subject_search_lookahead_days())
    return now - lookback, now + lookahead


def _normalize_search_bounds(
    date_from: datetime | None, date_to: datetime | None
) -> tuple[datetime, datetime]:
    """Fill in an omitted `from`/`to` bound so the adapter always receives
    concrete datetimes, using the configured lookback window as the
    default span when a bound is missing. Only ever called for a
    *partially* explicit range (exactly one of `from`/`to` given) —
    `calendar_search` routes the fully-omitted, subject-only case to
    `_subject_search_window()` instead (BUG-008 hotfix)."""
    now = _now()
    lookback = timedelta(days=_lookback_days())
    if date_from is None and date_to is None:
        return now - lookback, now
    if date_from is None:
        return date_to - lookback, date_to
    if date_to is None:
        return date_from, now
    return date_from, date_to


def calendar_search(request: SearchRequest, adapter: CalendarPort) -> CalendarSearchResult:
    """Search the calendar. Requires at least one of `from`/`to`/`subject`.

    `limit` (search-result-caps change, BUG-002) is resolved via
    `resolve_search_limit()` (default 50, hard max 200, `ValueError` when
    `<= 0`) before any adapter call. The adapter is expected to return up
    to `limit + 1` rows (the "+1 peek" convention) — this function slices
    to `limit` and sets `results_truncated` when the adapter's response
    exceeded it."""
    if request.date_from is None and request.date_to is None and not request.subject:
        raise ValueError(
            "calendar_search requires at least one filter: `from`, `to`, or `subject`"
        )
    # date-dasl-and-recurrence hotfix (2026-08-26, BUG-005 part 1): a
    # subject-only request has no explicit `from`/`to` — the concrete
    # bounds below are auto-filled purely so the adapter has something to
    # bound its Restrict()/recurrence-expansion window with, never as an
    # implicit date filter the caller asked for.
    explicit_date_bounds = request.date_from is not None or request.date_to is not None
    limit = resolve_search_limit(request.limit)
    window_applied: SearchWindow | None = None
    if explicit_date_bounds:
        date_from, date_to = _normalize_search_bounds(request.date_from, request.date_to)
    else:
        # BUG-008 hotfix (2026-08-26): a subject-only request (guaranteed
        # by the guard above, since `explicit_date_bounds` is False here)
        # gets the dedicated, symmetric, forward-leaning subject-search
        # window instead of the backward-only `lookback_days` default —
        # and the window actually used is reported back honestly so `[]`
        # can never again be mistaken for exhaustive.
        date_from, date_to = _subject_search_window()
        window_applied = SearchWindow(date_from=date_from, date_to=date_to)
    if date_from > date_to:
        # BUG-004 hotfix: an inverted range must never silently return an
        # empty result (the "the wrong answer is nothing" failure mode) —
        # echo both parsed bounds back so the caller can see exactly what
        # was resolved.
        raise ValueError(
            f"calendar_search date range is inverted: from={date_from.isoformat()} "
            f"is after to={date_to.isoformat()}"
        )
    results = adapter.search(
        date_from,
        date_to,
        subject=request.subject,
        limit=limit,
        enforce_date_bounds=explicit_date_bounds,
    )
    truncated = len(results) > limit
    return CalendarSearchResult(
        results=results[:limit],
        results_truncated=truncated,
        window_applied=window_applied,
    )


def calendar_get_event(request: GetEventRequest, adapter: CalendarPort) -> EventDetail:
    """Fetch full detail for a single event by its Outlook entryId."""
    return adapter.get_event(request.entry_id)


def calendar_get_notes(request: GetNotesRequest, adapter: CalendarPort) -> EventDetail:
    """Resolve the single note-appointment matching `date`+`subject` and
    return its full detail (subject + body)."""
    tz = local_timezone()
    day_start = datetime.combine(request.date, time(0, 0, 0), tzinfo=tz)
    day_end = datetime.combine(request.date, time(23, 59, 59), tzinfo=tz)

    matches = adapter.search(day_start, day_end, subject=request.subject)

    if not matches:
        raise EventNotFoundError(
            f"No calendar event found for date={request.date} subject={request.subject!r}"
        )
    if len(matches) > 1:
        raise AmbiguousMatchError(
            f"Multiple events match date={request.date} subject={request.subject!r}",
            entry_ids=[match.entry_id for match in matches],
        )
    return adapter.get_event(matches[0].entry_id)
