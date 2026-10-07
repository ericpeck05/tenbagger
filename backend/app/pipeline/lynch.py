"""The Lynch check: one of Peter Lynch's six categories, and a score out of 100 from nine tests.

Pure functions over a dict of inputs (a ratios row plus the sector), so every score can be
traced back to its inputs. A pass earns the test's full weight, a watch earns half, a fail
earns nothing. A test whose inputs are missing is left out and the remaining weights are
rescaled to 100. Thresholds live in lynch_config.py.
"""

from dataclasses import asdict, dataclass

from app.pipeline import lynch_config as cfg
from app.pipeline.sector import CYCLICAL, is_financial

CATEGORIES = ("Slow grower", "Stalwart", "Fast grower", "Cyclical", "Turnaround", "Asset play")


@dataclass
class Test:
    key: str
    label: str
    value: str | None  # shown on the page
    status: str  # pass, watch, fail, missing
    weight: int
    points: float  # earned before rescaling
    rule: str  # the thresholds, in words


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _big(x: float) -> str:
    for div, unit in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if abs(x) >= div:
            return f"{x / div:.2f}{unit}"
    return f"{x:,.0f}"


def _band(value: float | None, pass_ok: bool, watch_ok: bool) -> str:
    if value is None:
        return "missing"
    return "pass" if pass_ok else "watch" if watch_ok else "fail"


def _test(key: str, label: str, shown: str | None, status: str, rule: str) -> Test:
    weight = cfg.WEIGHTS[key]
    points = {"pass": weight, "watch": weight / 2}.get(status, 0.0)
    return Test(key, label, shown if status != "missing" else None, status, weight, points, rule)


def checks(r: dict, sic: int | None = None) -> list[Test]:
    """The nine tests for one company. `r` holds ratio values; missing ones are None."""
    out: list[Test] = []

    peg = r.get("peg")
    out.append(
        _test(
            "peg",
            "PEG under 1.0",
            f"{peg:.2f}" if peg is not None else None,
            _band(
                peg,
                peg is not None and peg < cfg.PEG_PASS_BELOW,
                peg is not None and peg < cfg.PEG_WATCH_BELOW,
            ),
            f"Pass under {cfg.PEG_PASS_BELOW}, watch under {cfg.PEG_WATCH_BELOW}",
        )
    )

    g = r.get("eps_growth_5y")
    out.append(
        _test(
            "eps_growth",
            "EPS growth above 15%",
            _pct(g) if g is not None else None,
            _band(
                g,
                g is not None and g > cfg.EPS_GROWTH_PASS_ABOVE,
                g is not None and g > cfg.EPS_GROWTH_WATCH_ABOVE,
            ),
            "5-year rate. Pass above 15%, watch 10% to 15%",
        )
    )

    pe = r.get("pe")
    lo, hi = cfg.PE_PASS
    out.append(
        _test(
            "pe",
            "P/E between 5 and 25",
            f"{pe:.1f}" if pe is not None else None,
            _band(
                pe,
                pe is not None and lo <= pe <= hi,
                pe is not None and cfg.PE_WATCH[0] < pe <= cfg.PE_WATCH[1],
            ),
            "Pass 5 to 25, watch 25 to 35",
        )
    )

    g1, g5 = r.get("revenue_growth_1y"), r.get("revenue_growth_5y")
    if g1 is None or g5 is None or g5 <= 0:
        status, shown = "missing", None
    else:
        ratio = g1 / g5
        status = _band(ratio, ratio >= cfg.REVENUE_HOLDING_PASS, ratio >= cfg.REVENUE_HOLDING_WATCH)
        shown = f"{_pct(g5)} to {_pct(g1)}"
    out.append(
        _test(
            "revenue_holding",
            "Revenue growth holding up",
            shown,
            status,
            "1-year growth against the 5-year rate. Pass at 90% or more, watch 60% to 90%",
        )
    )

    de = r.get("debt_to_equity")
    out.append(
        _test(
            "debt_to_equity",
            "Debt to equity under 0.5",
            f"{de:.2f}" if de is not None else None,
            _band(
                de,
                de is not None and de < cfg.DEBT_EQUITY_PASS_BELOW,
                de is not None and de < cfg.DEBT_EQUITY_WATCH_BELOW,
            ),
            "Pass under 0.5, watch 0.5 to 1.0",
        )
    )

    inv, rev = r.get("inventory_growth_1y"), r.get("revenue_growth_1y")
    if is_financial(sic) or inv is None or rev is None:
        status, shown = "missing", None
    else:
        status = _band(inv, inv < rev, inv <= rev + cfg.INVENTORY_WATCH_POINTS)
        shown = f"{_pct(inv)} vs {_pct(rev)}"
    out.append(
        _test(
            "inventory",
            "Inventory slower than sales",
            shown,
            status,
            "Inventory against sales growth over the last year. Watch if within 5 points faster. "
            "Skipped for banks and companies with no inventory",
        )
    )

    buys, sells = r.get("insider_buys_6m"), r.get("insider_sells_6m")
    if buys is None or sells is None:
        status, shown = "missing", None
    else:
        b, s = int(buys), int(sells)
        status = "pass" if b > s else "watch" if b == s == 0 else "fail"
        shown = f"{b} buy{'s' if b != 1 else ''}, {s} sell{'s' if s != 1 else ''}"
    out.append(
        _test(
            "insiders",
            "Insider buying, 6 months",
            shown,
            status,
            "Open-market buys (code P) against sales (code S) in Form 4 filings. "
            "Watch if there were none",
        )
    )

    mc = r.get("market_cap")
    out.append(
        _test(
            "market_cap",
            "Market cap 300M to 10B",
            _big(mc) if mc is not None else None,
            _band(
                mc,
                mc is not None and cfg.MARKET_CAP_PASS[0] <= mc <= cfg.MARKET_CAP_PASS[1],
                mc is not None and cfg.MARKET_CAP_WATCH[0] < mc <= cfg.MARKET_CAP_WATCH[1],
            ),
            "Pass 300M to 10B, watch 10B to 50B",
        )
    )

    cash, debt, ebitda = r.get("cash"), r.get("debt"), r.get("ebitda_ttm")
    if cash is None or debt is None:
        status, shown = "missing", None
    else:
        net_debt = debt - cash
        watch = (
            ebitda is not None
            and ebitda > 0
            and net_debt < cfg.NET_DEBT_EBITDA_WATCH_BELOW * ebitda
        )
        status = "pass" if cash > debt else "watch" if watch else "fail"
        per_share = r.get("net_cash_per_share")
        shown = f"{per_share:.2f} / sh" if per_share is not None else _big(cash - debt)
    out.append(
        _test(
            "net_cash",
            "Net cash is positive",
            shown,
            status,
            "Pass if cash exceeds debt, watch if net debt is under 1x EBITDA",
        )
    )
    return out


def score(results: list[Test]) -> float | None:
    """Points earned over points available, scaled to 100. None if every test is missing."""
    available = sum(t.weight for t in results if t.status != "missing")
    if available == 0:
        return None
    return round(100 * sum(t.points for t in results) / available, 1)


def category(r: dict, sector: str | None) -> str | None:
    """First matching category, or None if the company fits none (losses, no growth data)."""
    ni = r.get("net_income_ttm")
    if r.get("loss_recent") and ni is not None and (ni > 0 or r.get("loss_shrinking")):
        return "Turnaround"
    pb, price, ncps = r.get("price_to_book"), r.get("price"), r.get("net_cash_per_share")
    if (pb is not None and 0 < pb < cfg.ASSET_PLAY_MAX_PB) or (
        price and ncps is not None and ncps > cfg.ASSET_PLAY_NET_CASH_SHARE * price
    ):
        return "Asset play"
    drops = r.get("eps_drops_10y")
    if sector in CYCLICAL or (drops is not None and drops >= cfg.CYCLICAL_DROP_YEARS):
        return "Cyclical"
    g5, rev5 = r.get("eps_growth_5y"), r.get("revenue_growth_5y")
    if (
        g5 is not None
        and g5 >= cfg.FAST_GROWER_EPS_5Y
        and rev5 is not None
        and rev5 >= cfg.FAST_GROWER_REVENUE_5Y
    ):
        return "Fast grower"
    lo, hi = cfg.STALWART_EPS_5Y
    if g5 is not None and lo <= g5 < hi:
        return "Stalwart"
    eps = r.get("eps_ttm")
    if eps is not None and eps > 0:
        return "Slow grower"
    return None


def evaluate(r: dict, sector: str | None, sic: int | None) -> dict:
    results = checks(r, sic)
    return {
        "category": category(r, sector),
        "score": score(results),
        "tests": [asdict(t) for t in results],
    }


def history_flags(
    annual_ni: dict[int, float], annual_eps: dict[int, float], ni_ttm: float | None
) -> dict[str, float | None]:
    """Inputs the category rules need from the fiscal-year history.

    loss_recent: a net loss in either of the last two fiscal years.
    loss_shrinking: trailing net income is above the latest fiscal-year loss.
    eps_drops_10y: years in the last ten where EPS fell more than 30%.
    """
    years = sorted(annual_ni)
    recent = years[-cfg.TURNAROUND_LOOKBACK_YEARS :]
    losses = [annual_ni[y] for y in recent if annual_ni[y] < 0]
    latest_loss = (
        annual_ni[years[-1]]
        if years and annual_ni[years[-1]] < 0
        else (losses[-1] if losses else None)
    )
    eps_years = sorted(annual_eps)[-11:]
    drops = 0
    for a, b in zip(eps_years, eps_years[1:], strict=False):
        prev, cur = annual_eps[a], annual_eps[b]
        if prev > 0 and (cur - prev) / prev < -cfg.CYCLICAL_EPS_DROP:
            drops += 1
    return {
        "loss_recent": 1.0 if losses else 0.0 if years else None,
        "loss_shrinking": (
            1.0 if ni_ttm is not None and latest_loss is not None and ni_ttm > latest_loss else 0.0
        )
        if losses
        else None,
        "eps_drops_10y": float(drops) if len(eps_years) >= 3 else None,
    }
