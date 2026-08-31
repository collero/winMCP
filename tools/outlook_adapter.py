"""CalendarPort — the seam between tool logic and Outlook COM.

Defines the `CalendarPort` Protocol plus the real, win32com-backed
`OutlookCalendarAdapter`. The test-only `FakeCalendarAdapter`
(tools/fake_adapter.py) satisfies the same Protocol, which is what makes
RED-GREEN-REFACTOR possible on Linux with zero `win32com` dependency (see
design.md's "COM seam" decision).

`OutlookCalendarAdapter` imports `win32com.client` lazily, inside its own
methods — never at module scope — so this module (and therefore
`tools/calendar.py` and `server.py`, which import from it) stays importable
on Linux, per the outlook-com-adapter spec's "Lazy COM Import" requirement.
"""
from datetime import datetime
from typing import Any, Protocol

from models.schemas import EventDetail, EventSummary
from tools.errors import EventNotFoundError, OutlookUnavailableError
from tools.settings import load_settings, local_timezone

_DEFAULT_CALENDAR_FOLDER_ID = 9  # olFolderCalendar


class CalendarPort(Protocol):
    """Interface both the real and fake Outlook calendar adapters satisfy."""

    def search(
        self,
        date_from: datetime,
        date_to: datetime,
        subject: str | None = None,
        limit: int = 200,
        enforce_date_bounds: bool = True,
    ) -> list[EventSummary]:
        """Return calendar items whose range overlaps [date_from, date_to]
        and whose subject contains `subject` (case-insensitive), if given,
        newest-first, bounded to at most `limit + 1` rows
        (search-result-caps change, BUG-002's "+1 peek" convention — the
        tool layer slices to `limit` and flags `results_truncated` when it
        receives `limit + 1` rows back).

        `enforce_date_bounds` (date-dasl-and-recurrence hotfix, 2026-08-26,
        BUG-005 part 1): when `False`, the Python-side boundary re-check
        against `date_from`/`date_to` is skipped entirely — only the
        `Restrict()`-bounded window (still applied, so `IncludeRecurrences`
        expansion stays bounded) and the subject filter apply. The tool
        layer (`tools/calendar.py`) passes `False` for a subject-only
        request whose `date_from`/`date_to` were auto-filled from
        `lookback_days` rather than supplied by the caller, so a subject
        match is never silently dropped by a re-check against a window the
        caller never asked for. Defaults to `True` (the original,
        stricter, defense-in-depth behavior) for every explicit-bounds
        request."""
        ...

    def get_event(self, entry_id: str) -> EventDetail:
        """Return full detail for the calendar item identified by entry_id.

        Raises EventNotFoundError if entry_id does not resolve to an item,
        OutlookUnavailableError if Outlook cannot be reached at all.
        """
        ...


def _dasl_datetime(value: datetime) -> str:
    """Format a datetime for an Outlook `Items.Restrict()` DASL filter
    string literal, per design.md's Interfaces/Contracts note on the
    `"urn:schemas:calendar:dtstart" >= '...' AND "urn:schemas:calendar:
    dtend" <= '...'` format.

    Uses an ISO-ordered, 24-hour literal (`yyyy-mm-dd HH:MM`) rather than a
    locale-parsed `MM/DD/YYYY hh:mm AM/PM` string (this fixes BUG-003's
    upper-bound case). BUG-004 (2026-08-26 live evidence) showed this ISO
    literal is STILL not safe when compared via Jet's bracket-property
    Restrict() syntax (`[Start] >= '...'`) under es-ES: the lower bound of
    a range kept reading as day/month-transposed whenever its day was
    <= 12, silently inverting the range to an empty result. `search()`
    below therefore compares this literal via `@SQL=` DASL syntax against
    a quoted property URN instead of a bare bracket property name — DASL
    date-literal comparisons are documented as culture-invariant,
    regardless of the Outlook client's locale (design.md's "DASL @SQL=
    Restrict" decision, the date-dasl-and-recurrence hotfix)."""
    return value.strftime("%Y-%m-%d %H:%M")


def _to_aware(value: Any, tz: Any) -> datetime:
    """Attach a timezone to a naive datetime returned by Outlook COM.

    Outlook COM (`pywintypes.datetime`) returns times in the Outlook
    profile's local timezone with no explicit offset — design.md's
    "Datetime handling" decision requires attaching one at this boundary.
    Already-aware values (e.g. real pywintypes.datetime, which subclasses
    Python's datetime and may already carry tzinfo) pass through unchanged.
    """
    if value.tzinfo is not None:
        return value
    return value.replace(tzinfo=tz)


class OutlookCalendarAdapter:
    """Real Outlook COM-backed `CalendarPort` implementation.

    Connects via `win32com.client.Dispatch("Outlook.Application")` ->
    `GetNamespace("MAPI")` -> `GetDefaultFolder(id)`, per the
    outlook-com-adapter spec's "Real Adapter COM Access" requirement. The
    folder id is resolved from `config/settings.yaml`'s `calendar_folder_id`
    at COM-access time (default `9`, olFolderCalendar, when absent) — see
    the "Configurable Folder Ids" requirement.
    """

    def _resolve_folder_id(self) -> int:
        """Read `calendar_folder_id` from settings at COM-access time
        (never cached), falling back to `_DEFAULT_CALENDAR_FOLDER_ID` when
        the key is absent or settings.yaml is unreadable."""
        try:
            settings = load_settings()
        except Exception:
            return _DEFAULT_CALENDAR_FOLDER_ID
        return int(settings.get("calendar_folder_id", _DEFAULT_CALENDAR_FOLDER_ID))

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
        date_from: datetime,
        date_to: datetime,
        subject: str | None = None,
        limit: int = 200,
        enforce_date_bounds: bool = True,
    ) -> list[EventSummary]:
        outlook = self._dispatch_outlook()
        try:
            namespace = outlook.GetNamespace("MAPI")
            folder = namespace.GetDefaultFolder(self._resolve_folder_id())
            items = folder.Items
            items.IncludeRecurrences = True
            # Ascending (oldest-first), NOT descending — date-dasl-and-
            # recurrence hotfix (2026-08-26, BUG-005 part 2). Outlook COM
            # only expands a recurring series' occurrences through
            # Restrict()/Find() when IncludeRecurrences=True AND the source
            # collection was Sort()ed ascending by [Start] first; sorting
            # descending (as the search-result-caps change, BUG-002, did
            # for an early-stop optimization) silently breaks recurrence
            # expansion, dropping every occurrence of every recurring
            # series. Newest-first output is now produced by sorting the
            # small, already Restrict()-bounded match list in Python,
            # after collection below.
            items.Sort("[Start]", False)
            # BUG-004 hotfix: DASL `@SQL=` syntax against a quoted property
            # URN, not Jet's bare bracket-property syntax (`[Start] >=
            # '...'`) — the latter still locale-parses even an ISO-ordered
            # literal under es-ES, transposing day/month on the lower bound
            # and silently inverting the range. See `_dasl_datetime`'s
            # docstring for the live evidence.
            restrict = (
                f'@SQL="urn:schemas:calendar:dtstart" >= \'{_dasl_datetime(date_from)}\' '
                f'AND "urn:schemas:calendar:dtend" <= \'{_dasl_datetime(date_to)}\''
            )
            restricted = items.Restrict(restrict)
        except Exception as exc:
            raise OutlookUnavailableError(
                f"Outlook calendar search failed: {exc}"
            ) from exc

        tz = local_timezone()
        # datetime-tz hotfix (2026-08-26): normalize the request bounds
        # through the same `_to_aware` helper used for COM values below.
        # `SearchRequest.date_from`/`date_to` (models/schemas.py) have no
        # tz-aware validator, so a naive bound can reach here even though
        # real Outlook COM's `item.Start`/`item.End` (`pywintypes.datetime`)
        # are already timezone-aware with a fixed offset on real Windows —
        # comparing an aware `start`/`end` against a naive `date_from`/
        # `date_to` raised "can't compare offset-naive and offset-aware
        # datetimes" in production. `_to_aware` is a no-op when the value
        # is already aware, so this is safe regardless of which side (or
        # neither) was naive.
        date_from = _to_aware(date_from, tz)
        date_to = _to_aware(date_to, tz)
        subject_needle = subject.lower() if subject else None
        results: list[EventSummary] = []
        for item in restricted:
            start = _to_aware(item.Start, tz)
            end = _to_aware(item.End, tz)
            # Defense-in-depth boundary re-check (design.md's "Python-side
            # post-filter as defense-in-depth" decision): drop any item
            # Restrict() over-included, guarding against any residual
            # locale-parsing surprise in the DASL literal that this dev
            # host cannot verify against real Outlook. Compares each
            # OCCURRENCE's own Start/End (never a recurring series'
            # master), and is skipped entirely when `enforce_date_bounds`
            # is `False` (date-dasl-and-recurrence hotfix, BUG-005 part
            # 1) — a subject-only request's date_from/date_to are an
            # auto-filled lookback window the caller never asked for, so
            # they must bound the Restrict()/recurrence-expansion window
            # only, never drop an otherwise-matching item.
            if enforce_date_bounds and (start < date_from or end > date_to):
                continue
            item_subject = item.Subject
            if subject_needle is not None and subject_needle not in item_subject.lower():
                continue
            results.append(
                EventSummary(
                    entry_id=item.EntryID,
                    subject=item_subject,
                    start=start,
                    end=end,
                )
            )
        # Newest-first (search-result-caps change, BUG-002), applied here
        # in Python instead of relying on COM-source ordering — the source
        # is now ascending (see the Sort() note above), and Restrict()
        # already bounds the window, so this collected list is expected to
        # be small. "+1 peek" convention preserved: `limit + 1` rows lets
        # the tool layer detect `results_truncated` from the length alone.
        results.sort(key=lambda summary: summary.start, reverse=True)
        return results[: limit + 1]

    def get_event(self, entry_id: str) -> EventDetail:
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
            raise EventNotFoundError(
                f"No event with entryId {entry_id!r}: {exc}"
            ) from exc

        if item is None:
            raise EventNotFoundError(f"No event with entryId {entry_id!r}")

        tz = local_timezone()
        return EventDetail(
            entry_id=item.EntryID,
            subject=item.Subject,
            start=_to_aware(item.Start, tz),
            end=_to_aware(item.End, tz),
            body=item.Body or "",
        )
