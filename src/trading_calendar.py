"""Small, explicit NYSE session calendar used by the forward paper workflow.

The calendar covers the recurring full-day US exchange holidays used by the
current forward protocol.  Exceptional exchange closures remain an operational
calendar update and must be added before the affected session is processed.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from pandas.tseries.holiday import (
    AbstractHolidayCalendar,
    GoodFriday,
    Holiday,
    MO,
    TH,
    nearest_workday,
)
from pandas.tseries.offsets import DateOffset


NEW_YORK = ZoneInfo("America/New_York")


class _NYSERecurringHolidays(AbstractHolidayCalendar):
    rules = [
        Holiday("New Year's Day", month=1, day=1, observance=nearest_workday),
        Holiday(
            "Martin Luther King Jr. Day",
            month=1,
            day=1,
            offset=DateOffset(weekday=MO(3)),
            start_date="1998-01-01",
        ),
        Holiday(
            "Washington's Birthday",
            month=2,
            day=1,
            offset=DateOffset(weekday=MO(3)),
        ),
        GoodFriday,
        Holiday(
            "Memorial Day",
            month=5,
            day=31,
            offset=DateOffset(weekday=MO(-1)),
        ),
        Holiday(
            "Juneteenth National Independence Day",
            month=6,
            day=19,
            observance=nearest_workday,
            start_date="2022-01-01",
        ),
        Holiday("Independence Day", month=7, day=4, observance=nearest_workday),
        Holiday(
            "Labor Day",
            month=9,
            day=1,
            offset=DateOffset(weekday=MO(1)),
        ),
        Holiday(
            "Thanksgiving",
            month=11,
            day=1,
            offset=DateOffset(weekday=TH(4)),
        ),
        Holiday("Christmas", month=12, day=25, observance=nearest_workday),
    ]


_HOLIDAYS = _NYSERecurringHolidays()


def _day(value: str | date | datetime | pd.Timestamp) -> date:
    return pd.Timestamp(value).date()


def holiday_dates(start: str | date, end: str | date) -> set[date]:
    return {stamp.date() for stamp in _HOLIDAYS.holidays(start=start, end=end)}


def is_session(value: str | date | datetime | pd.Timestamp) -> bool:
    candidate = _day(value)
    if candidate.weekday() >= 5:
        return False
    return candidate not in holiday_dates(candidate - timedelta(days=7), candidate + timedelta(days=7))


def next_session(value: str | date | datetime | pd.Timestamp, steps: int = 1) -> date:
    if steps < 1:
        raise ValueError("steps must be at least one")
    candidate = _day(value)
    found = 0
    while found < steps:
        candidate += timedelta(days=1)
        if is_session(candidate):
            found += 1
    return candidate


def previous_session(value: str | date | datetime | pd.Timestamp, steps: int = 1) -> date:
    if steps < 1:
        raise ValueError("steps must be at least one")
    candidate = _day(value)
    found = 0
    while found < steps:
        candidate -= timedelta(days=1)
        if is_session(candidate):
            found += 1
    return candidate


def last_session_of_month(year: int, month: int) -> date:
    month_end = (pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd()).date()
    candidate = month_end
    while not is_session(candidate):
        candidate -= timedelta(days=1)
    return candidate


def is_month_end_session(value: str | date | datetime | pd.Timestamp) -> bool:
    candidate = _day(value)
    return is_session(candidate) and candidate == last_session_of_month(candidate.year, candidate.month)


def is_early_close(value: str | date | datetime | pd.Timestamp) -> bool:
    """Return recurring 13:00 ET closes; exceptional notices remain fail-closed ops data."""
    candidate = _day(value)
    if not is_session(candidate):
        return False
    thanksgiving = Holiday(
        "Thanksgiving", month=11, day=1, offset=DateOffset(weekday=TH(4))
    ).dates(f"{candidate.year}-01-01", f"{candidate.year}-12-31")[0].date()
    if candidate == thanksgiving + timedelta(days=1):
        return True
    if candidate.month == 12 and candidate.day == 24:
        return True
    july_fourth = date(candidate.year, 7, 4)
    probe = july_fourth - timedelta(days=1)
    while not is_session(probe):
        probe -= timedelta(days=1)
    return candidate == probe


def session_open(value: str | date | datetime | pd.Timestamp) -> datetime:
    candidate = _day(value)
    if not is_session(candidate):
        raise ValueError(f"{candidate.isoformat()} is not an NYSE session")
    return datetime.combine(candidate, time(9, 30), tzinfo=NEW_YORK)


def session_close(value: str | date | datetime | pd.Timestamp) -> datetime:
    candidate = _day(value)
    if not is_session(candidate):
        raise ValueError(f"{candidate.isoformat()} is not an NYSE session")
    close_time = time(13, 0) if is_early_close(candidate) else time(16, 0)
    return datetime.combine(candidate, close_time, tzinfo=NEW_YORK)
