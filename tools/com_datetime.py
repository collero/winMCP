"""from_com_datetime — the ONE conversion every Outlook COM datetime read
passes through (BUG-010, mail/0001-0002, live-discriminated 2026-08-31).

Outlook COM item date properties (`ReceivedTime`, `SentOn`,
`LastModificationTime`, `Start`, `End`, `DueDate`, ...) return LOCAL
wall-clock values that pywin32 wraps in a bogus fixed-UTC tzinfo
(`TimeZoneInfo('GMT Standard Time', True)`) — the digits are local, the
label lies. Ground truth from the live probes: a February inbox message's
`ReceivedTime` read `13:43:18 "UTC"` while its true-UTC MAPI property
(`PR_MESSAGE_DELIVERY_TIME`) said `12:43:18` — one hour off in winter, two
in summer, i.e. exactly the local offset. The MAPI store itself is
correct; only the COM read label is wrong.

This helper therefore REINTERPRETS: it strips whatever tzinfo the value
carries, attaches the real local timezone (`tools/settings.py::
local_timezone()` — honors `timezone_override`), and converts to true UTC.
It also folds in the year-4501 `olNoDate` sentinel guard (an UNSET COM
date is a truthy datetime, not None — `tools/task_adapter.py` has guarded
its DueDate this way since birth; the guard belongs in the one shared
place, and `mail_adapter._resolve_date`'s falsy check was a latent trap
without it).

USE FOR COM-READ VALUES ONLY. Caller-supplied bounds (request dateFrom/
dateTo) are honestly labeled and must keep going through each adapter's
`_to_aware` — reinterpreting an honest UTC bound would corrupt it.
"""
from datetime import datetime, timezone
from typing import Any

# Outlook's olNoDate sentinel is 4501-01-01; anything in that era means
# "unset", never a real timestamp.
_NO_DATE_SENTINEL_YEAR = 4500


def from_com_datetime(value: Any, tz: Any) -> datetime | None:
    """Convert a raw Outlook-COM datetime read into a TRUE-UTC aware
    datetime, or `None` for absent/unset values. `tz` is the real local
    timezone (pass `local_timezone()`)."""
    if not value:
        return None
    if not isinstance(value, datetime):
        return None
    if value.year >= _NO_DATE_SENTINEL_YEAR:
        return None
    return value.replace(tzinfo=tz).astimezone(timezone.utc)
