"""US market hours: 9:30 a.m. to 4:00 p.m. New York time on weekdays, minus NYSE holidays."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
OPEN = time(9, 30)
CLOSE = time(16, 0)
EARLY_CLOSE = time(13, 0)

# NYSE full-day closures. Update once a year from nyse.com/markets/hours-calendars.
HOLIDAYS = {
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3),
    date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7),
    date(2026, 11, 26), date(2026, 12, 25),
    date(2027, 1, 1), date(2027, 1, 18), date(2027, 2, 15), date(2027, 3, 26),
    date(2027, 5, 31), date(2027, 6, 18), date(2027, 7, 5), date(2027, 9, 6),
    date(2027, 11, 25), date(2027, 12, 24),
}  # fmt: skip
EARLY_CLOSES = {date(2026, 11, 27), date(2026, 12, 24), date(2027, 11, 26)}


def now_ny() -> datetime:
    return datetime.now(NY)


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in HOLIDAYS


def close_time(d: date) -> time:
    return EARLY_CLOSE if d in EARLY_CLOSES else CLOSE


def is_open(at: datetime | None = None) -> bool:
    at = (at or now_ny()).astimezone(NY)
    return is_trading_day(at.date()) and OPEN <= at.time() < close_time(at.date())


def last_trading_day(before: date) -> date:
    d = before - timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


def latest_complete_session(at: datetime | None = None) -> date:
    """The most recent trading day whose closing bar exists (Alpaca's SIP delay included)."""
    at = (at or now_ny()).astimezone(NY)
    today = at.date()
    done = datetime.combine(today, close_time(today), NY) + timedelta(minutes=20)
    if is_trading_day(today) and at >= done:
        return today
    return last_trading_day(today)


def last_close_at(at: datetime | None = None) -> datetime:
    """The moment of the most recent market close, as an aware datetime."""
    at = (at or now_ny()).astimezone(NY)
    d = at.date()
    if is_trading_day(d) and at.time() >= close_time(d):
        return datetime.combine(d, close_time(d), NY)
    prev = last_trading_day(d)
    return datetime.combine(prev, close_time(prev), NY)
