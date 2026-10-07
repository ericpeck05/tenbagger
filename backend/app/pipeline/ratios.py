"""Step 3 of the fundamentals pipeline: ratio formulas.

A ratio with a missing input is None, never zero. Ratios whose denominator is zero or
negative in a way that makes the number meaningless (negative equity, losses) are None too.

`fundamentals()` builds a snapshot of the latest figures from a company's facts.
`filing_ratios()` computes everything that does not need a price; it changes only when a
filing does. `price_ratios()` adds the price-based ratios and runs whenever a quote arrives.
"""

from dataclasses import asdict, dataclass, field
from datetime import date

from app.pipeline import ttm as T
from app.pipeline.tags import Fact

Facts = dict[str, dict[tuple, Fact]]

TAX_RATE_CAP = 0.35


@dataclass
class Fundamentals:
    """The latest figures one company's filings support."""

    as_of: date | None = None  # end of the latest period with data
    ttm_basis: str | None = None
    # Trailing twelve months
    revenue: float | None = None
    cost_of_revenue: float | None = None
    gross_profit: float | None = None
    operating_income: float | None = None
    pretax_income: float | None = None
    income_tax: float | None = None
    net_income: float | None = None
    eps: float | None = None
    depreciation_amortization: float | None = None
    interest_expense: float | None = None
    operating_cash_flow: float | None = None
    capex: float | None = None
    dividends_per_share: float | None = None
    # Latest balance sheet
    cash: float | None = None
    debt: float | None = None
    equity: float | None = None
    equity_year_ago: float | None = None
    total_assets: float | None = None
    current_assets: float | None = None
    current_liabilities: float | None = None
    inventory: float | None = None
    inventory_year_ago: float | None = None
    shares_outstanding: float | None = None
    # Fiscal-year history, oldest first, for growth rates and the trend chart
    annual: dict[str, dict[int, float]] = field(default_factory=dict)


TTM_METRICS = (
    "revenue",
    "cost_of_revenue",
    "gross_profit",
    "operating_income",
    "pretax_income",
    "income_tax",
    "net_income",
    "depreciation_amortization",
    "interest_expense",
    "operating_cash_flow",
    "capex",
    "dividends_per_share",
)
BALANCE_METRICS = (
    "cash",
    "debt",
    "equity",
    "total_assets",
    "current_assets",
    "current_liabilities",
    "inventory",
)
ANNUAL_METRICS = (
    "revenue",
    "net_income",
    "eps_diluted",
    "operating_cash_flow",
    "capex",
    "dividends_per_share",
    "shares_diluted",
)


def fundamentals(facts: Facts) -> Fundamentals:
    out = Fundamentals()
    ends: list[date] = []

    for name in TTM_METRICS:
        t = T.ttm(facts.get(name, {}))
        if t is not None:
            setattr(out, name, t.value)
            ends.append(t.end)
            if name == "revenue":
                out.ttm_basis = t.basis
    out.eps = _checked_eps(T.ttm(facts.get("eps_diluted", {})), out.net_income, facts)

    # Balance sheet items are read at the latest balance sheet date. An item last reported
    # on an older balance sheet (debt that was paid off, say) is missing, not stale.
    sheet = T.latest(facts.get("total_assets", {})) or T.latest(facts.get("equity", {}))
    if sheet is not None:
        ends.append(sheet.end)
        for name in BALANCE_METRICS:
            f = T.at(facts.get(name, {}), sheet.end)
            setattr(out, name, f.value if f else None)
        for name in ("equity", "inventory"):
            prior = T.year_earlier(facts.get(name, {}), sheet.end)
            setattr(out, f"{name}_year_ago", prior.value if prior else None)

    out.shares_outstanding = _shares(facts)
    out.as_of = max(ends) if ends else None

    for name in ANNUAL_METRICS:
        out.annual[name] = {y: f.value for y, f in sorted(T.annual(facts.get(name, {})).items())}
    out.annual["equity"] = _annual_instants(facts.get("equity", {}), facts)
    out.annual["inventory"] = _annual_instants(facts.get("inventory", {}), facts)
    out.annual["shares_outstanding"] = _annual_instants(facts.get("shares_outstanding", {}), facts)
    return out


EPS_TOLERANCE = 2.0  # reported and derived trailing EPS may differ by this factor


def _checked_eps(eps: T.Trailing | None, net_income: float | None, facts: Facts) -> float | None:
    """Trailing EPS, cross-checked so a stock split inside the window cannot distort it.

    Trailing EPS adds a fiscal year to year-to-date figures. When a split lands inside that
    window, the 10-K's figure is on the old share basis and the newer 10-Q's on the new one,
    and the sum is meaningless (a 1-for-250 reverse split can turn a loss into a huge
    "profit"). The latest 10-Q's own net income and EPS for the same period give the share
    basis it reports on, so trailing net income over that share count is a consistent
    figure. If the two disagree in sign or by more than 2x, the derived one is used.
    Share-count tags are not used for this: some filers tag them in millions.
    """
    if eps is None or eps.basis == "FY" or net_income is None:
        return eps.value if eps else None
    ytd_eps = _ytd(facts.get("eps_diluted", {}), eps.end)
    ytd_ni = _ytd(facts.get("net_income", {}), eps.end)
    if ytd_eps is None or ytd_ni is None or abs(ytd_eps) < 0.005 or ytd_ni == 0:
        return eps.value
    derived = net_income * ytd_eps / ytd_ni
    ratio = eps.value / derived if derived else 0
    if ratio <= 0 or not 1 / EPS_TOLERANCE <= ratio <= EPS_TOLERANCE:
        return derived
    return eps.value


def _ytd(facts: dict[tuple, Fact], end: date) -> float | None:
    """The longest year-to-date value ending on `end`."""
    ytd = [f for f in facts.values() if f.end == end and T.ytd_months(f) is not None]
    return max(ytd, key=lambda f: f.days).value if ytd else None


def _shares(facts: Facts) -> float | None:
    """Shares outstanding, falling back to the latest diluted share count."""
    f = T.latest(facts.get("shares_outstanding", {}))
    if f is not None:
        return f.value
    diluted = facts.get("shares_diluted", {})
    if not diluted:
        return None
    return max(diluted.values(), key=lambda f: (f.end, f.filed)).value


def _fiscal_year_ends(facts: Facts) -> dict[int, date]:
    ends: dict[int, date] = {}
    for name in ("revenue", "net_income", "operating_cash_flow"):
        for year, f in T.annual(facts.get(name, {})).items():
            ends.setdefault(year, f.end)
    return ends


def _annual_instants(series: dict[tuple, Fact], facts: Facts) -> dict[int, float]:
    """Point-in-time values at each fiscal year end."""
    out = {}
    for year, end in sorted(_fiscal_year_ends(facts).items()):
        near = [f for f in series.values() if abs((f.end - end).days) <= 31]
        if near:
            out[year] = min(near, key=lambda f: abs((f.end - end).days)).value
    return out


# ---------------------------------------------------------------- formulas


def _div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


def _pos_div(a: float | None, b: float | None) -> float | None:
    """a / b when b is positive; ratios against a negative base are not meaningful."""
    return _div(a, b) if b is not None and b > 0 else None


def cagr(start: float | None, end: float | None, years: int) -> float | None:
    """Compound annual growth. Blank if either end is zero or negative."""
    if start is None or end is None or start <= 0 or end <= 0 or years <= 0:
        return None
    return (end / start) ** (1 / years) - 1


def growth(series: dict[int, float], years: int) -> float | None:
    """Growth per year over `years` fiscal years, ending at the latest year."""
    if not series:
        return None
    last = max(series)
    return cagr(series.get(last - years), series.get(last), years)


def free_cash_flow(f: Fundamentals) -> float | None:
    if f.operating_cash_flow is None or f.capex is None:
        return None
    return f.operating_cash_flow - f.capex


def ebitda(f: Fundamentals, financial: bool = False) -> float | None:
    if financial or f.operating_income is None or f.depreciation_amortization is None:
        return None
    return f.operating_income + f.depreciation_amortization


def tax_rate(f: Fundamentals) -> float | None:
    rate = _pos_div(f.income_tax, f.pretax_income)
    return None if rate is None else min(max(rate, 0.0), TAX_RATE_CAP)


def _positive(*values: float | None) -> bool:
    return all(v is not None and v > 0 for v in values)


def _avg(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else (a + b) / 2


def _annual_fcf(f: Fundamentals) -> dict[int, float]:
    ocf, capex = f.annual.get("operating_cash_flow", {}), f.annual.get("capex", {})
    return {y: ocf[y] - capex[y] for y in ocf if y in capex}


def _annual_bvps(f: Fundamentals) -> dict[int, float]:
    eq, sh = f.annual.get("equity", {}), f.annual.get("shares_outstanding", {})
    return {y: eq[y] / sh[y] for y in eq if sh.get(y)}


def filing_ratios(f: Fundamentals, financial: bool = False) -> dict[str, float | None]:
    """Every ratio that needs no price. `financial` marks banks and insurers."""
    fcf = free_cash_flow(f)
    e = ebitda(f, financial)
    rate = tax_rate(f)
    net_cash = None if f.cash is None or f.debt is None else f.cash - f.debt
    invested = (
        None if f.equity is None or f.debt is None or f.cash is None else f.equity + f.debt - f.cash
    )
    nopat = None if f.operating_income is None or rate is None else f.operating_income * (1 - rate)
    gross = None if financial else f.gross_profit

    out: dict[str, float | None] = {
        "revenue_ttm": f.revenue,
        "net_income_ttm": f.net_income,
        "eps_ttm": f.eps,
        "ebitda_ttm": e,
        "fcf_ttm": fcf,
        "dps_ttm": f.dividends_per_share,
        "gross_margin": _pos_div(gross, f.revenue),
        "operating_margin": _pos_div(f.operating_income, f.revenue),
        "net_margin": _pos_div(f.net_income, f.revenue),
        "roe": _pos_div(f.net_income, _avg(f.equity, f.equity_year_ago))
        if _positive(f.equity, f.equity_year_ago)
        else None,
        "roic": _pos_div(nopat, invested),
        "cash_conversion": _pos_div(fcf, f.net_income),
        "debt_to_equity": _pos_div(f.debt, f.equity),
        "net_cash": net_cash,
        "net_cash_per_share": _pos_div(net_cash, f.shares_outstanding),
        "net_debt_ebitda": None if net_cash is None else _pos_div(-net_cash, e),
        "current_ratio": None if financial else _pos_div(f.current_assets, f.current_liabilities),
        "interest_coverage": _pos_div(f.operating_income, f.interest_expense),
        "inventory_turnover": _pos_div(f.cost_of_revenue, _avg(f.inventory, f.inventory_year_ago)),
    }

    series = {
        "revenue": f.annual.get("revenue", {}),
        "eps": f.annual.get("eps_diluted", {}),
        "fcf": _annual_fcf(f),
        "bvps": _annual_bvps(f),
        "inventory": f.annual.get("inventory", {}),
        "shares": f.annual.get("shares_diluted", {}),
    }
    for name, s in series.items():
        for years in (1, 3, 5):
            out[f"{name}_growth_{years}y"] = growth(s, years)
    return out


# A trailing P/E under 1 means a year's earnings exceed the share price. No real stock trades
# there; it is a per-share figure tagged on the wrong basis in a filing, so P/E and PEG are
# left blank rather than shown.
MIN_PLAUSIBLE_PE = 1.0

PRICE_RATIOS = (
    "market_cap",
    "pe",
    "peg",
    "price_to_sales",
    "price_to_book",
    "enterprise_value",
    "ev_ebitda",
    "fcf_yield",
    "dividend_yield",
)


def price_ratios(
    price: float | None,
    r: dict,
    shares: float | None,
    equity: float | None,
    debt: float | None,
    cash: float | None,
) -> dict[str, float | None]:
    """Ratios that move with the price. `r` holds the output of `filing_ratios`."""
    if price is None or price <= 0:
        return dict.fromkeys(PRICE_RATIOS)
    mcap = None if shares is None else price * shares
    pe = _pos_div(price, r.get("eps_ttm"))
    if pe is not None and pe < MIN_PLAUSIBLE_PE:
        pe = None  # earnings above the whole share price: a tagging error in the filing
    g = r.get("eps_growth_5y")
    if g is None:
        g = r.get("eps_growth_3y")
    ev = None if mcap is None or debt is None or cash is None else mcap + debt - cash
    return {
        "market_cap": mcap,
        "pe": pe,
        "peg": None if pe is None or g is None or g <= 0 else pe / (g * 100),
        "price_to_sales": _pos_div(mcap, r.get("revenue_ttm")),
        "price_to_book": _pos_div(mcap, equity),
        "enterprise_value": ev,
        "ev_ebitda": _pos_div(ev, r.get("ebitda_ttm")),
        "fcf_yield": _div(r.get("fcf_ttm"), mcap),
        "dividend_yield": _div(r.get("dps_ttm"), price),
    }


def as_dict(f: Fundamentals) -> dict:
    return asdict(f)
