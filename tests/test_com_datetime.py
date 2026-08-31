"""RED/GREEN tests for tools/com_datetime.py — the ONE conversion every
Outlook COM datetime read passes through (BUG-010, mail/0001-0002).

Live-proven facts this helper encodes (2026-08-31 probes):
- Outlook COM item date properties return LOCAL wall-clock; pywin32 wraps
  them in a bogus UTC-ish tzinfo. Ground truth: a February inbox message
  read `13:43:18 "UTC"` while its true-UTC MAPI property said `12:43:18`
  (1h off in winter); today's drafts read 2h off. The wall-clock digits
  are LOCAL; the label lies.
- Unset COM dates are a TRUTHY year-4501 sentinel (e.g. a draft's SentOn),
  not None — tools/task_adapter.py has guarded this for its DueDate since
  birth; the guard belongs in the one shared place.
- Caller-supplied bounds must NEVER pass through this helper — it
  REINTERPRETS aware values, which is correct only for COM reads.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from tools.com_datetime import from_com_datetime

MADRID = ZoneInfo("Europe/Madrid")


# Stand-in for pywintypes' TimeZoneInfo('GMT Standard Time', True): a
# fixed zero-offset tzinfo whose name is not "UTC".
_FAKE_UTC_LABEL = timezone(timedelta(0), "GMT Standard Time")


def test_summer_mislabeled_value_reinterpreted_as_local_and_converted_to_utc():
    # cowork's draft: created 15:25:42Z true, COM read 17:25:52 "UTC"
    mislabeled = datetime(2026, 8, 31, 17, 25, 52, 373000, tzinfo=_FAKE_UTC_LABEL)

    result = from_com_datetime(mislabeled, MADRID)

    assert result == datetime(2026, 8, 31, 15, 25, 52, 373000, tzinfo=timezone.utc)
    assert result.tzinfo == timezone.utc


def test_winter_mislabeled_value_shifts_by_one_hour_not_two():
    # the February inbox message: COM 13:43:18 "UTC", true UTC 12:43:18
    mislabeled = datetime(2026, 2, 25, 13, 43, 18, 584000, tzinfo=_FAKE_UTC_LABEL)

    result = from_com_datetime(mislabeled, MADRID)

    assert result == datetime(2026, 2, 25, 12, 43, 18, 584000, tzinfo=timezone.utc)


def test_naive_value_attaches_local_then_converts():
    naive = datetime(2026, 8, 31, 17, 25, 52)

    result = from_com_datetime(naive, MADRID)

    assert result == datetime(2026, 8, 31, 15, 25, 52, tzinfo=timezone.utc)


def test_year_4501_sentinel_is_none():
    sentinel = datetime(4501, 1, 1, tzinfo=_FAKE_UTC_LABEL)

    assert from_com_datetime(sentinel, MADRID) is None


def test_none_is_none():
    assert from_com_datetime(None, MADRID) is None


def test_falsy_non_datetime_is_none():
    assert from_com_datetime("", MADRID) is None
