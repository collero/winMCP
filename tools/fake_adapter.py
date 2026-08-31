"""FakeCalendarAdapter — in-memory CalendarPort implementation used by tests.

Seeded via the constructor with a list of `EventDetail` (summary fields +
body). Implements the same `CalendarPort` Protocol as the real win32com-backed
adapter, so tool code under test never knows the difference — this is what
lets the full Strict TDD RED-GREEN-REFACTOR cycle run on WSL2 Linux with zero
`win32com` dependency (see design.md's "COM seam" decision).
"""
from datetime import datetime

from models.schemas import EventDetail, EventSummary
from tools.errors import EventNotFoundError, OutlookUnavailableError


class FakeCalendarAdapter:
    """In-memory stand-in for `OutlookCalendarAdapter`, satisfying `CalendarPort`."""

    def __init__(
        self,
        events: list[EventDetail] | None = None,
        *,
        unavailable: bool = False,
    ):
        self._events = list(events) if events else []
        self._unavailable = unavailable

    def search(
        self,
        date_from: datetime,
        date_to: datetime,
        subject: str | None = None,
        limit: int = 200,
        enforce_date_bounds: bool = True,
    ) -> list[EventSummary]:
        if self._unavailable:
            raise OutlookUnavailableError(
                "Outlook is not available (fake adapter configured to fail)"
            )

        subject_needle = subject.lower() if subject else None
        matches: list[EventSummary] = []
        for event in self._events:
            # Overlap test: event range intersects [date_from, date_to].
            # Skipped entirely when `enforce_date_bounds=False`
            # (date-dasl-and-recurrence hotfix, BUG-005 part 1) — mirrors
            # OutlookCalendarAdapter.search()'s boundary re-check skip for
            # a subject-only request's auto-filled lookback window.
            if enforce_date_bounds and (event.end < date_from or event.start > date_to):
                continue
            if subject_needle is not None and subject_needle not in event.subject.lower():
                continue
            matches.append(
                EventSummary(
                    entry_id=event.entry_id,
                    subject=event.subject,
                    start=event.start,
                    end=event.end,
                )
            )
        # search-result-caps (BUG-002): mirrors OutlookCalendarAdapter's
        # newest-first ordering + `limit + 1` "+1 peek" bounding exactly.
        matches.sort(key=lambda summary: summary.start, reverse=True)
        return matches[: limit + 1]

    def get_event(self, entry_id: str) -> EventDetail:
        if self._unavailable:
            raise OutlookUnavailableError(
                "Outlook is not available (fake adapter configured to fail)"
            )

        for event in self._events:
            if event.entry_id == entry_id:
                return event
        raise EventNotFoundError(f"No event with entryId {entry_id!r}")
