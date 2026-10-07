"""Portfolio math: replay the trade log into positions, and build time-weighted returns.

Pure functions over plain data, so the math can be checked by hand in the tests.

Rules:
- Average cost. A buy adds shares and their cost. A sell removes shares at the average
  cost and books the difference as a realized gain.
- Cash comes only from the log. A buy that costs more than the cash on hand is treated as
  money brought in for it (an implicit deposit), so logging trades without deposits still
  gives correct returns.
- Returns are time-weighted, so money coming in or going out is never a gain or a loss.
  With V the day's closing value and F the net money brought in that day:

      r_t = (V_t - F_t) / V_(t-1) - 1
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date

TYPES = ("buy", "sell", "deposit", "withdrawal", "dividend")
EPSILON = 1e-9


class TradeError(ValueError):
    """A trade the log cannot accept, such as selling shares that are not held."""


@dataclass(frozen=True)
class Trade:
    date: date
    type: str
    ticker: str | None = None
    shares: float | None = None
    price: float | None = None
    amount: float = 0.0  # cash moved; for buys and sells, shares x price
    id: int = 0


@dataclass
class Position:
    shares: float = 0.0
    cost: float = 0.0  # total cost basis of the shares held

    @property
    def avg_cost(self) -> float | None:
        return self.cost / self.shares if self.shares > EPSILON else None


@dataclass
class Book:
    positions: dict[str, Position] = field(default_factory=dict)
    cash: float = 0.0
    net_deposits: float = 0.0  # money brought in minus money taken out, implicit included
    realized: float = 0.0
    dividends: float = 0.0

    @property
    def cost_basis(self) -> float:
        return sum(p.cost for p in self.positions.values())

    def held(self) -> dict[str, Position]:
        return {t: p for t, p in self.positions.items() if p.shares > EPSILON}


def validate(t: Trade) -> None:
    if t.type not in TYPES:
        raise TradeError(f"Unknown type {t.type!r}")
    if t.type in ("buy", "sell"):
        if not t.ticker:
            raise TradeError("A buy or sell needs a ticker")
        if not t.shares or t.shares <= 0:
            raise TradeError("Shares must be more than zero")
        if t.price is None or t.price < 0:
            raise TradeError("Price must be zero or more")
    elif t.amount <= 0:
        raise TradeError("Amount must be more than zero")


def apply(book: Book, t: Trade) -> float:
    """Apply one trade. Returns the money brought in or taken out (the day's flow)."""
    validate(t)
    if t.type == "buy":
        assert t.ticker and t.shares and t.price is not None
        cost = t.shares * t.price
        flow = max(cost - book.cash, 0.0)  # implicit deposit for any shortfall
        book.cash += flow - cost
        book.net_deposits += flow
        pos = book.positions.setdefault(t.ticker, Position())
        pos.shares += t.shares
        pos.cost += cost
        return flow
    if t.type == "sell":
        assert t.ticker and t.shares and t.price is not None
        pos = book.positions.get(t.ticker)
        held = pos.shares if pos else 0.0
        if t.shares > held + EPSILON:
            raise TradeError(f"Cannot sell {t.shares:g} {t.ticker} on {t.date}: only {held:g} held")
        assert pos is not None
        avg = pos.cost / pos.shares
        book.realized += t.shares * (t.price - avg)
        pos.cost -= t.shares * avg
        pos.shares -= t.shares
        if pos.shares <= EPSILON:
            pos.shares, pos.cost = 0.0, 0.0
        book.cash += t.shares * t.price
        return 0.0
    if t.type == "deposit":
        book.cash += t.amount
        book.net_deposits += t.amount
        return t.amount
    if t.type == "withdrawal":
        if t.amount > book.cash + EPSILON:
            raise TradeError(
                f"Cannot withdraw {t.amount:,.2f} on {t.date}: only {book.cash:,.2f} in cash"
            )
        book.cash -= t.amount
        book.net_deposits -= t.amount
        return -t.amount
    # dividend: cash received, counts toward return
    book.cash += t.amount
    book.dividends += t.amount
    return 0.0


def ordered(trades: Iterable[Trade]) -> list[Trade]:
    """Trades in the order they happened. Same-day cash comes in before buys spend it."""
    rank = {"deposit": 0, "dividend": 1, "sell": 2, "buy": 3, "withdrawal": 4}
    return sorted(trades, key=lambda t: (t.date, rank[t.type], t.id))


def replay(trades: Iterable[Trade]) -> Book:
    book = Book()
    for t in ordered(trades):
        apply(book, t)
    return book


@dataclass(frozen=True)
class Day:
    date: date
    value: float
    cash: float
    net_deposits: float
    return_index: float


def daily(
    trades: Iterable[Trade],
    days: list[date],
    close: Callable[[str, date], float | None],
) -> list[Day]:
    """Value and time-weighted return index for each trading day from the first trade.

    `close(ticker, day)` gives the latest close on or before the day. A holding with no
    close yet is valued at the price it was bought at.
    """
    trades = ordered(trades)
    if not trades:
        return []
    start = trades[0].date
    days = [d for d in days if d >= start]
    book = Book()
    last_price: dict[str, float] = {}
    out: list[Day] = []
    i = 0
    prev_value = 0.0
    index = 1.0
    for d in days:
        flow = 0.0
        while i < len(trades) and trades[i].date <= d:
            t = trades[i]
            flow += apply(book, t)
            if t.ticker and t.price is not None:
                last_price[t.ticker] = t.price
            i += 1
        value = book.cash
        for ticker, pos in book.held().items():
            px = close(ticker, d)
            if px is None:
                px = last_price.get(ticker, 0.0)
            value += pos.shares * px
        if prev_value > EPSILON:
            index *= (value - flow) / prev_value
        out.append(Day(d, value, book.cash, book.net_deposits, index))
        prev_value = value
    return out
