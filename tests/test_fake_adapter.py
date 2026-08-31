"""RED tests for tools/fake_adapter.py — FakeCalendarAdapter (test-only CalendarPort).

Covers: search() filters by date range and case-insensitive subject substring;
get_event() returns a match or raises EventNotFoundError; both methods can be
configured to raise OutlookUnavailableError instead (simulating COM Dispatch
failure) without ever touching real Outlook/win32com.
"""
from datetime import datetime, timezone

import pytest

from models.schemas import EventDetail
from tools.errors import EventNotFoundError, OutlookUnavailableError
from tools.fake_adapter import FakeCalendarAdapter


def _event(entry_id: str, subject: str, hour: int, body: str = "") -> EventDetail:
    return EventDetail(
        entry_id=entry_id,
        subject=subject,
        start=datetime(2026, 7, 27, hour, 0, tzinfo=timezone.utc),
        end=datetime(2026, 7, 27, hour, 30, tzinfo=timezone.utc),
        body=body,
    )


SEEDED_EVENTS = [
    _event("ABC123", "Tareas (bloque)", 9, body="Politica ADN"),
    _event("ABC124", "Reflexiones", 11, body="..."),
    _event("ABC125", "Tareas (otro dia)", 9),
]


def test_search_filters_by_date_range_and_subject_substring_case_insensitive():
    adapter = FakeCalendarAdapter(events=SEEDED_EVENTS[:2])

    results = adapter.search(
        date_from=datetime(2026, 7, 27, 0, 0, tzinfo=timezone.utc),
        date_to=datetime(2026, 7, 27, 23, 59, tzinfo=timezone.utc),
        subject="tareas",
    )

    assert len(results) == 1
    assert results[0].entry_id == "ABC123"
    assert results[0].subject == "Tareas (bloque)"


def test_search_excludes_events_outside_date_range():
    adapter = FakeCalendarAdapter(events=SEEDED_EVENTS)

    results = adapter.search(
        date_from=datetime(2026, 7, 28, 0, 0, tzinfo=timezone.utc),
        date_to=datetime(2026, 7, 28, 23, 59, tzinfo=timezone.utc),
        subject="tareas",
    )

    assert results == []


def test_get_event_returns_matching_detail():
    adapter = FakeCalendarAdapter(events=SEEDED_EVENTS)

    detail = adapter.get_event("ABC123")

    assert detail.entry_id == "ABC123"
    assert detail.body == "Politica ADN"


def test_get_event_raises_not_found_for_unknown_entry_id():
    adapter = FakeCalendarAdapter(events=SEEDED_EVENTS)

    with pytest.raises(EventNotFoundError):
        adapter.get_event("DOES-NOT-EXIST")


def test_search_raises_outlook_unavailable_when_configured():
    adapter = FakeCalendarAdapter(events=SEEDED_EVENTS, unavailable=True)

    with pytest.raises(OutlookUnavailableError):
        adapter.search(
            date_from=datetime(2026, 7, 27, 0, 0, tzinfo=timezone.utc),
            date_to=datetime(2026, 7, 27, 23, 59, tzinfo=timezone.utc),
        )


def test_get_event_raises_outlook_unavailable_when_configured():
    adapter = FakeCalendarAdapter(events=SEEDED_EVENTS, unavailable=True)

    with pytest.raises(OutlookUnavailableError):
        adapter.get_event("ABC123")


# ---------------------------------------------------------------------------
# search-result-caps (BUG-002): FakeCalendarAdapter mirrors
# OutlookCalendarAdapter's newest-first ordering + `limit + 1` "+1 peek"
# bounding exactly.
# ---------------------------------------------------------------------------

def _day_event(entry_id: str, subject: str, day: int) -> EventDetail:
    return EventDetail(
        entry_id=entry_id,
        subject=subject,
        start=datetime(2026, 8, day, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 8, day, 9, 30, tzinfo=timezone.utc),
        body="",
    )


_OUT_OF_ORDER_EVENTS = [
    _day_event("E-AUG10", "Reunion", 10),
    _day_event("E-AUG1", "Reunion", 1),
    _day_event("E-AUG20", "Reunion", 20),
]


def test_search_returns_newest_first():
    adapter = FakeCalendarAdapter(events=_OUT_OF_ORDER_EVENTS)

    results = adapter.search(
        date_from=datetime(2026, 8, 1, tzinfo=timezone.utc),
        date_to=datetime(2026, 8, 31, tzinfo=timezone.utc),
        subject="reunion",
    )

    assert [r.entry_id for r in results] == ["E-AUG20", "E-AUG10", "E-AUG1"]


def test_search_bounds_to_limit_plus_one():
    adapter = FakeCalendarAdapter(events=_OUT_OF_ORDER_EVENTS)

    results = adapter.search(
        date_from=datetime(2026, 8, 1, tzinfo=timezone.utc),
        date_to=datetime(2026, 8, 31, tzinfo=timezone.utc),
        subject="reunion",
        limit=1,
    )

    assert [r.entry_id for r in results] == ["E-AUG20", "E-AUG10"]


def test_search_returns_all_when_under_limit_plus_one():
    adapter = FakeCalendarAdapter(events=_OUT_OF_ORDER_EVENTS)

    results = adapter.search(
        date_from=datetime(2026, 8, 1, tzinfo=timezone.utc),
        date_to=datetime(2026, 8, 31, tzinfo=timezone.utc),
        subject="reunion",
        limit=50,
    )

    assert [r.entry_id for r in results] == ["E-AUG20", "E-AUG10", "E-AUG1"]
