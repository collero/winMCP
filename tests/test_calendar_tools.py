"""Tests for tools/calendar.py — the tool-layer functions for the three
Outlook calendar MCP tools (calendar_search, calendar_get_event,
calendar_get_notes), exercised against FakeCalendarAdapter.

Phase 4: calendar_search (calendar-search spec)
Phase 5: calendar_get_event (calendar-get-event spec)
Phase 6: calendar_get_notes (calendar-get-notes spec)
BUG-008 hotfix (2026-08-26): subject-only search's default window is now
a dedicated, symmetric, forward-leaning window
(`calendar_subject_search_lookback_days`/`..._lookahead_days`), echoed
back honestly via `CalendarSearchResult.window_applied` — see the tests
below tagged BUG-008.
"""
from datetime import date, datetime, timedelta, timezone

import pytest

from models.schemas import EventDetail, GetEventRequest, GetNotesRequest, SearchRequest
from tools.calendar import calendar_get_event, calendar_get_notes, calendar_search
from tools.errors import AmbiguousMatchError, EventNotFoundError, OutlookUnavailableError
from tools.fake_adapter import FakeCalendarAdapter


def _event(entry_id: str, subject: str, hour: int, body: str = "") -> EventDetail:
    return EventDetail(
        entry_id=entry_id,
        subject=subject,
        start=datetime(2026, 7, 27, hour, 0, tzinfo=timezone.utc),
        end=datetime(2026, 7, 27, hour, 30, tzinfo=timezone.utc),
        body=body,
    )


# ---------------------------------------------------------------------------
# Phase 4: calendar_search
# ---------------------------------------------------------------------------


def test_search_valid_range_and_subject(mocker):
    events = [
        _event("ABC123", "Tareas (bloque)", 9, body="Politica ADN"),
        _event("ABC124", "Reflexiones", 11),
        _event("ABC125", "Otra cosa", 14),
    ]
    adapter = FakeCalendarAdapter(events=events)
    spy = mocker.spy(adapter, "search")

    date_from = datetime(2026, 7, 27, 0, 0, tzinfo=timezone.utc)
    date_to = datetime(2026, 7, 27, 23, 59, 59, tzinfo=timezone.utc)
    request = SearchRequest(date_from=date_from, date_to=date_to, subject="tareas")

    result = calendar_search(request, adapter)

    # search-result-caps: `limit` is now also threaded through, resolved
    # via `resolve_search_limit(None)` -> the default 50.
    # date-dasl-and-recurrence hotfix: explicit `from`/`to` given ->
    # `enforce_date_bounds=True`.
    spy.assert_called_once_with(
        date_from, date_to, subject="tareas", limit=50, enforce_date_bounds=True
    )
    assert len(result.results) == 1
    assert result.results[0].entry_id == "ABC123"
    assert result.results_truncated is False


def test_search_rejects_no_filters(mocker):
    adapter = FakeCalendarAdapter(events=[])
    spy = mocker.spy(adapter, "search")
    request = SearchRequest()

    with pytest.raises(ValueError, match="filter"):
        calendar_search(request, adapter)

    spy.assert_not_called()


def test_search_empty_result_returns_empty_list():
    adapter = FakeCalendarAdapter(events=[])
    request = SearchRequest(subject="Nonexistent")

    result = calendar_search(request, adapter)

    assert result.results == []
    assert result.results_truncated is False
    # BUG-008: an empty subject-only result must not read as byte-identical
    # to "no such appointment" — the window that was actually searched must
    # be echoed back.
    assert result.window_applied is not None


def test_search_outlook_unavailable_returns_tool_error():
    adapter = FakeCalendarAdapter(events=[], unavailable=True)
    request = SearchRequest(subject="Tareas")

    with pytest.raises(OutlookUnavailableError):
        calendar_search(request, adapter)


def test_search_wide_window_bounded_to_default_limit_and_flagged(mocker):
    """search-result-caps (BUG-002) spec's "Wide window is bounded to the
    default limit" scenario."""
    mocker.patch("tools.settings.load_settings", return_value={})
    events = [
        _event(f"E{i}", "tareas", 9 + (i % 10)) for i in range(240)
    ]
    adapter = FakeCalendarAdapter(events=events)
    date_from = datetime(2026, 5, 1, tzinfo=timezone.utc)
    date_to = datetime(2026, 8, 1, tzinfo=timezone.utc)
    request = SearchRequest(date_from=date_from, date_to=date_to, subject="tareas")

    result = calendar_search(request, adapter)

    assert len(result.results) <= 50
    assert result.results_truncated is True


def test_search_limit_above_hard_max_clamped_to_200_not_rejected(mocker):
    mocker.patch("tools.settings.load_settings", return_value={})
    events = [_event(f"E{i}", "tareas", 9) for i in range(300)]
    adapter = FakeCalendarAdapter(events=events)
    spy = mocker.spy(adapter, "search")
    date_from = datetime(2026, 7, 1, tzinfo=timezone.utc)
    date_to = datetime(2026, 7, 31, tzinfo=timezone.utc)
    request = SearchRequest(date_from=date_from, date_to=date_to, limit=500)

    result = calendar_search(request, adapter)

    assert spy.call_args.kwargs["limit"] == 200
    assert len(result.results) == 200
    assert result.results_truncated is True


def test_search_non_positive_limit_rejected_before_adapter_call(mocker):
    adapter = FakeCalendarAdapter(events=[])
    spy = mocker.spy(adapter, "search")
    request = SearchRequest(subject="x", limit=-1)

    with pytest.raises(ValueError):
        calendar_search(request, adapter)

    spy.assert_not_called()


def test_search_out_of_order_source_items_returned_newest_first():
    """spec's "Out-of-order source items are returned newest-first"
    scenario, exercised at the calendar_search tool boundary."""
    events = [
        _event("E-AUG10", "tareas", 9),
        _event("E-AUG1", "tareas", 9),
        _event("E-AUG20", "tareas", 9),
    ]
    events[0] = events[0].model_copy(
        update={
            "start": datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
            "end": datetime(2026, 8, 10, 9, 30, tzinfo=timezone.utc),
        }
    )
    events[1] = events[1].model_copy(
        update={
            "start": datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc),
            "end": datetime(2026, 8, 1, 9, 30, tzinfo=timezone.utc),
        }
    )
    events[2] = events[2].model_copy(
        update={
            "start": datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc),
            "end": datetime(2026, 8, 20, 9, 30, tzinfo=timezone.utc),
        }
    )
    adapter = FakeCalendarAdapter(events=events)
    date_from = datetime(2026, 8, 1, tzinfo=timezone.utc)
    date_to = datetime(2026, 8, 31, tzinfo=timezone.utc)
    request = SearchRequest(date_from=date_from, date_to=date_to, subject="tareas")

    result = calendar_search(request, adapter)

    assert [e.entry_id for e in result.results] == ["E-AUG20", "E-AUG10", "E-AUG1"]


def test_search_defaults_missing_bounds_using_subject_search_window(mocker):
    """BUG-008 hotfix: a subject-only request (from/to both omitted) must
    reach the adapter with concrete, normalized datetimes (design.md
    handoff note: CalendarPort.search() requires non-optional
    date_from/date_to) drawn from the dedicated, symmetric,
    forward-leaning subject-search window
    (`calendar_subject_search_lookback_days`/`..._lookahead_days` —
    default 90 back / 365 forward) rather than the old backward-only
    `lookback_days` default, and the resolved window must be echoed back
    via `window_applied`."""
    frozen_now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    mocker.patch("tools.calendar._now", return_value=frozen_now)
    adapter = FakeCalendarAdapter(events=[])
    spy = mocker.spy(adapter, "search")
    request = SearchRequest(subject="Tareas")

    result = calendar_search(request, adapter)

    spy.assert_called_once()
    called_from, called_to = spy.call_args.args
    assert called_from.tzinfo is not None
    assert called_to.tzinfo is not None
    assert called_from < called_to
    assert called_from == frozen_now - timedelta(days=90)
    assert called_to == frozen_now + timedelta(days=365)
    # date-dasl-and-recurrence hotfix (BUG-005 part 1): a subject-only
    # request's auto-filled bounds must not enforce a date boundary
    # re-check inside the adapter.
    assert spy.call_args.kwargs["enforce_date_bounds"] is False
    # BUG-008: the applied window must be reported back honestly.
    assert result.window_applied is not None
    assert result.window_applied.date_from == called_from
    assert result.window_applied.date_to == called_to


def test_search_explicit_bounds_enforce_date_bounds_true(mocker):
    """Mirror of the above: when the caller supplies an explicit `from`/
    `to`, the boundary re-check must stay enforced."""
    adapter = FakeCalendarAdapter(events=[])
    spy = mocker.spy(adapter, "search")
    request = SearchRequest(
        date_from=datetime(2026, 7, 27, 0, 0, tzinfo=timezone.utc),
        date_to=datetime(2026, 7, 27, 23, 59, 59, tzinfo=timezone.utc),
    )

    result = calendar_search(request, adapter)

    assert spy.call_args.kwargs["enforce_date_bounds"] is True
    # BUG-008: an explicit-bounds request never had a window silently
    # applied, so `window_applied` must stay unset.
    assert result.window_applied is None


def test_search_inverted_range_raises_value_error_echoing_both_bounds():
    """BUG-004 hotfix: an inverted explicit range must raise, never
    silently return an empty result."""
    adapter = FakeCalendarAdapter(events=[])
    request = SearchRequest(
        date_from=datetime(2026, 6, 10, 0, 0, tzinfo=timezone.utc),
        date_to=datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc),
    )

    with pytest.raises(ValueError, match="inverted") as exc_info:
        calendar_search(request, adapter)

    assert "2026-06-10" in str(exc_info.value)
    assert "2026-06-01" in str(exc_info.value)


def test_search_subject_only_finds_event_far_outside_default_lookback_window():
    """Regression for BUG-005 part 1's live evidence ("AGC-COS" et al.):
    a subject-only search must find a matching event even when its date
    falls well outside the default `lookback_days` window."""
    far_future_event = _event("FAR-FUTURE", "AGC-COS", 10)
    far_future_event = far_future_event.model_copy(
        update={
            "start": datetime(2030, 1, 1, 10, 0, tzinfo=timezone.utc),
            "end": datetime(2030, 1, 1, 10, 30, tzinfo=timezone.utc),
        }
    )
    adapter = FakeCalendarAdapter(events=[far_future_event])
    request = SearchRequest(subject="AGC-COS")

    result = calendar_search(request, adapter)

    assert [e.entry_id for e in result.results] == ["FAR-FUTURE"]


def test_search_subject_only_finds_past_and_future_occurrences_under_new_defaults(mocker):
    """BUG-008 regression, encoding the live verifier's exact evidence: a
    subject-only search must find both an appointment ~2 months in the
    past ("Cumpleanos Ada", 22 June — outside the old 7-day `lookback_days`
    default) and one tomorrow ("AGC-COS" — which the old backward-only
    default could never see at all, since it never looked past "now").
    Dates are fixed relative to a frozen `_now`, never wall-clock."""
    frozen_now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    mocker.patch("tools.calendar._now", return_value=frozen_now)
    past_start = frozen_now - timedelta(days=60)
    tomorrow_start = frozen_now + timedelta(days=1)
    past_event = _event("PAST", "Cumpleanos Ada", 10).model_copy(
        update={"start": past_start, "end": past_start + timedelta(minutes=30)}
    )
    tomorrow_event = _event("TOMORROW", "AGC-COS", 10).model_copy(
        update={"start": tomorrow_start, "end": tomorrow_start + timedelta(minutes=30)}
    )
    adapter = FakeCalendarAdapter(events=[past_event, tomorrow_event])

    past_result = calendar_search(SearchRequest(subject="Cumpleanos Ada"), adapter)
    tomorrow_result = calendar_search(SearchRequest(subject="AGC-COS"), adapter)

    assert [e.entry_id for e in past_result.results] == ["PAST"]
    assert [e.entry_id for e in tomorrow_result.results] == ["TOMORROW"]


def test_search_subject_self_consistency_outside_default_window(mocker):
    """Amended self-consistency regression (BUG-008, superseding the
    0041-style version): taking a date query's result and subject-searching
    it only proves the window logic works if the date query's window falls
    OUTSIDE the subject-search default — inside the default it passes by
    luck regardless of whether the window is correct. Seeds an event
    beyond the new 365-day-forward default, finds it via an explicit-bounds
    date query, then subject-searches it: the result must either come back
    or the response must explicitly report the window that excluded it."""
    frozen_now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    mocker.patch("tools.calendar._now", return_value=frozen_now)
    far_start = frozen_now + timedelta(days=400)  # beyond the 365-day default
    far_event = _event("FAR", "Congreso Anual", 9).model_copy(
        update={"start": far_start, "end": far_start + timedelta(minutes=30)}
    )
    adapter = FakeCalendarAdapter(events=[far_event])
    date_request = SearchRequest(
        date_from=frozen_now + timedelta(days=395),
        date_to=frozen_now + timedelta(days=405),
    )

    date_result = calendar_search(date_request, adapter)
    assert date_result.results  # sanity: the explicit-bounds query found it
    found_subject = date_result.results[0].subject

    subject_result = calendar_search(SearchRequest(subject=found_subject), adapter)

    found_in_results = found_subject.lower() in {
        r.subject.lower() for r in subject_result.results
    }
    reported_out_of_window = (
        subject_result.window_applied is not None
        and subject_result.window_applied.date_to < far_start
    )
    assert found_in_results or reported_out_of_window


def test_search_wider_range_is_superset_of_narrower_contained_range():
    """Superset-containment regression (BUG-004's recommended property
    test): any range's results must be a superset of every sub-range it
    contains."""
    events = [
        _event(f"E-{day:02d}", "tareas", 9).model_copy(
            update={
                "start": datetime(2026, 1, day, 9, 0, tzinfo=timezone.utc),
                "end": datetime(2026, 1, day, 9, 30, tzinfo=timezone.utc),
            }
        )
        for day in range(1, 29)
    ]
    adapter = FakeCalendarAdapter(events=events)

    wide_request = SearchRequest(
        date_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        date_to=datetime(2026, 1, 28, 23, 59, 59, tzinfo=timezone.utc),
        subject="tareas",
        limit=200,
    )
    narrow_request = SearchRequest(
        date_from=datetime(2026, 1, 8, tzinfo=timezone.utc),
        date_to=datetime(2026, 1, 19, 23, 59, 59, tzinfo=timezone.utc),
        subject="tareas",
        limit=200,
    )

    wide_ids = {e.entry_id for e in calendar_search(wide_request, adapter).results}
    narrow_ids = {e.entry_id for e in calendar_search(narrow_request, adapter).results}

    assert narrow_ids <= wide_ids
    assert narrow_ids == {f"E-{day:02d}" for day in range(8, 20)}


def test_search_recurring_series_all_occurrences_returned_within_window():
    """Fake-level recurrence regression (BUG-005 part 2): a recurring-style
    series seeded as several occurrences sharing a subject must all be
    returned for a window that spans them, alongside a one-off event."""
    weekday_occurrences = [
        _event(f"BTS-{day}", "BtS", 8).model_copy(
            update={
                "start": datetime(2026, 8, day, 8, 0, tzinfo=timezone.utc),
                "end": datetime(2026, 8, day, 9, 30, tzinfo=timezone.utc),
            }
        )
        for day in (24, 25, 26, 27, 28)
    ]
    one_off = _event("AGC-COS", "AGC-COS", 10).model_copy(
        update={
            "start": datetime(2026, 8, 27, 10, 0, tzinfo=timezone.utc),
            "end": datetime(2026, 8, 27, 10, 30, tzinfo=timezone.utc),
        }
    )
    adapter = FakeCalendarAdapter(events=[*weekday_occurrences, one_off])
    request = SearchRequest(
        date_from=datetime(2026, 8, 24, tzinfo=timezone.utc),
        date_to=datetime(2026, 8, 28, 23, 59, 59, tzinfo=timezone.utc),
        limit=200,
    )

    result = calendar_search(request, adapter)

    assert {e.entry_id for e in result.results} == {
        "BTS-24", "BTS-25", "BTS-26", "BTS-27", "BTS-28", "AGC-COS",
    }


# ---------------------------------------------------------------------------
# Phase 5: calendar_get_event
# ---------------------------------------------------------------------------


def test_get_event_success():
    detail = _event("ABC123", "Tareas (bloque)", 9, body="Politica ADN\nMarco IA Responsable")
    adapter = FakeCalendarAdapter(events=[detail])
    request = GetEventRequest(entry_id="ABC123")

    result = calendar_get_event(request, adapter)

    assert result.entry_id == "ABC123"
    assert result.subject == "Tareas (bloque)"
    assert result.body == "Politica ADN\nMarco IA Responsable"
    assert result.start == detail.start
    assert result.end == detail.end


def test_get_event_not_found_raises_tool_error():
    adapter = FakeCalendarAdapter(events=[])
    request = GetEventRequest(entry_id="BAD-ID")

    with pytest.raises(EventNotFoundError):
        calendar_get_event(request, adapter)


def test_get_event_empty_body_returns_empty_string():
    detail = _event("XYZ789", "No notes", 9, body="")
    adapter = FakeCalendarAdapter(events=[detail])
    request = GetEventRequest(entry_id="XYZ789")

    result = calendar_get_event(request, adapter)

    assert result.body == ""
    assert result.subject == "No notes"


# ---------------------------------------------------------------------------
# Phase 6: calendar_get_notes
# ---------------------------------------------------------------------------


def test_get_notes_expands_date_to_full_day_range_local_tz(mocker):
    detail = _event("ABC123", "Tareas (bloque)", 9, body="Politica ADN")
    adapter = FakeCalendarAdapter(events=[detail])
    spy = mocker.spy(adapter, "search")
    request = GetNotesRequest(date=date(2026, 7, 27), subject="Tareas")

    calendar_get_notes(request, adapter)

    spy.assert_called_once()
    called_from, called_to = spy.call_args.args
    called_kwargs = spy.call_args.kwargs
    local_tz = datetime.now().astimezone().tzinfo
    assert called_from == datetime(2026, 7, 27, 0, 0, 0, tzinfo=local_tz)
    assert called_to == datetime(2026, 7, 27, 23, 59, 59, tzinfo=local_tz)
    assert called_kwargs == {"subject": "Tareas"}


def test_get_notes_single_match_returns_subject_and_body():
    detail = _event("ABC123", "Tareas (bloque)", 9, body="Politica ADN\nMarco IA Responsable")
    adapter = FakeCalendarAdapter(events=[detail])
    request = GetNotesRequest(date=date(2026, 7, 27), subject="Tareas")

    result = calendar_get_notes(request, adapter)

    assert result.subject == "Tareas (bloque)"
    assert result.body == "Politica ADN\nMarco IA Responsable"


def test_get_notes_zero_matches_raises_not_found():
    adapter = FakeCalendarAdapter(events=[])
    request = GetNotesRequest(date=date(2026, 7, 27), subject="Nonexistent")

    with pytest.raises(EventNotFoundError):
        calendar_get_notes(request, adapter)


def test_get_notes_multiple_matches_raises_ambiguous_lists_entry_ids_no_get_event_call(mocker):
    events = [
        _event("ABC123", "Tareas (bloque)", 9),
        _event("ABC124", "Tareas (otro bloque)", 11),
    ]
    adapter = FakeCalendarAdapter(events=events)
    get_event_spy = mocker.spy(adapter, "get_event")
    request = GetNotesRequest(date=date(2026, 7, 27), subject="Tareas")

    with pytest.raises(AmbiguousMatchError) as exc_info:
        calendar_get_notes(request, adapter)

    assert set(exc_info.value.entry_ids) == {"ABC123", "ABC124"}
    get_event_spy.assert_not_called()
