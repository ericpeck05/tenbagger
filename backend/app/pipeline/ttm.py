"""Step 2 of the fundamentals pipeline: clean periods and trailing twelve months.

Periods come from each fact's own start and end dates, never from the filing's `fy` and
`fp` fields, which describe the filing rather than the number. Income and cash flow facts in
a 10-Q are year-to-date figures, so:

    TTM = last fiscal year + current year-to-date - same year-to-date a year earlier
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

from app.pipeline.tags import Fact

# Day-count windows. 52/53-week fiscal years run 364 or 371 days.
FY_DAYS = (350, 380)
# A year-to-date period runs from the fiscal year start to a quarter end. Most quarters are
# 13 weeks, but some retailers use 16-week first or third quarters, so the window is wide.
YTD_DAYS = (75, 300)
ALIGN_TOLERANCE = 7  # days between a fiscal year end and the next period's start
YEAR_TOLERANCE = 12  # days of slack when looking for "the same date a year earlier"


def is_annual(f: Fact) -> bool:
    return f.start is not None and FY_DAYS[0] <= f.days <= FY_DAYS[1]


def ytd_months(f: Fact) -> int | None:
    """Approximate length in months of a year-to-date period: 3, 6, or 9 (or 4, 7, ...)."""
    if f.start is None or not YTD_DAYS[0] <= f.days <= YTD_DAYS[1]:
        return None
    return round(f.days / 30.44)


def fiscal_year(end: date) -> int:
    """Name a fiscal year by the calendar year it ends in.

    52/53-week years that end in the first week of January belong to the year before.
    """
    return end.year - 1 if end.month == 1 and end.day <= 7 else end.year


def annual(facts: dict[tuple, Fact]) -> dict[int, Fact]:
    """Fiscal-year values keyed by fiscal year, latest period winning on a clash."""
    out: dict[int, Fact] = {}
    for f in sorted((f for f in facts.values() if is_annual(f)), key=lambda f: f.end):
        out[fiscal_year(f.end)] = f
    return out


def _near(a: date, b: date, days: int) -> bool:
    return abs((a - b).days) <= days


@dataclass(frozen=True)
class Trailing:
    value: float
    end: date
    basis: str  # "FY" when the latest figure is a fiscal year, else e.g. "FY+9M"


def ttm(facts: dict[tuple, Fact]) -> Trailing | None:
    """Trailing twelve months for a duration metric, or None if it cannot be built."""
    years = [f for f in facts.values() if is_annual(f)]
    if not years:
        return None
    fy = max(years, key=lambda f: f.end)
    next_start = fy.end + timedelta(days=1)

    current = [
        f
        for f in facts.values()
        if f.start is not None
        and f.end > fy.end
        and ytd_months(f) is not None
        and _near(f.start, next_start, ALIGN_TOLERANCE)
    ]
    if not current:
        return Trailing(fy.value, fy.end, "FY")

    cur = max(current, key=lambda f: f.end)
    months = ytd_months(cur)
    prior = [
        f
        for f in facts.values()
        if f.start is not None
        and ytd_months(f) is not None
        and abs(f.days - cur.days) <= 10
        and _near(f.start, fy.start, ALIGN_TOLERANCE)  # type: ignore[arg-type]
        and _near(f.end, cur.end - timedelta(days=365), YEAR_TOLERANCE)
    ]
    if not prior:
        return None
    prev = max(prior, key=lambda f: f.filed)
    return Trailing(fy.value + cur.value - prev.value, cur.end, f"FY+{months}M")


def latest(facts: dict[tuple, Fact]) -> Fact | None:
    """Most recent point-in-time value."""
    if not facts:
        return None
    return max(facts.values(), key=lambda f: (f.end, f.filed))


def at(facts: dict[tuple, Fact], end: date, tolerance: int = 3) -> Fact | None:
    """Point-in-time value on `end`, give or take a few days."""
    near = [f for f in facts.values() if _near(f.end, end, tolerance)]
    return max(near, key=lambda f: f.filed) if near else None


def year_earlier(facts: dict[tuple, Fact], end: date) -> Fact | None:
    """Point-in-time value closest to one year before `end`, within a few weeks."""
    target = end - timedelta(days=365)
    near = [f for f in facts.values() if _near(f.end, target, 31)]
    return min(near, key=lambda f: abs((f.end - target).days)) if near else None


def fiscal_period_label(f: Fact, fiscal_year_ends: Iterable[date]) -> str | None:
    """FY for a full year, Q1 to Q3 for a year-to-date period, else None.

    Balance sheet values get the label of the period they close, if any.
    """
    ends = list(fiscal_year_ends)
    if f.start is None:
        return "FY" if any(_near(f.end, e, 3) for e in ends) else None
    if is_annual(f):
        return "FY"
    if ytd_months(f) and any(_near(f.start, e + timedelta(days=1), ALIGN_TOLERANCE) for e in ends):
        return f"Q{min(max(round(f.days / 91), 1), 3)}"
    return None
