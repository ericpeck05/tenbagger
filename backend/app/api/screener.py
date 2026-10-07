"""Screener: filter and sort every company on any stored ratio, sector, and Lynch category.

One SQL query over the ratios table (one row per company), so a screen across the whole
market is a single indexed read.

    GET /api/screener?f=peg:lt:1&f=market_cap:between:3e8,1e10&category=Fast grower
        &sort=lynch_score&dir=desc&limit=100

Filter values are in stored units: fractions for percentages (0.15 is 15%), dollars for money.
"""

import json
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, asc, desc, func, select
from sqlalchemy.orm import Session

from app.db.models import Company, Quote, Ratio, Screen
from app.db.session import DbSession
from app.pipeline.pricing import utcnow

router = APIRouter()

# key: (label, kind). kind tells the page how to show and enter values.
FIELDS: dict[str, tuple[str, str]] = {
    "lynch_score": ("Lynch score", "score"),
    "market_cap": ("Market cap", "money"),
    "price": ("Price", "price"),
    "pe": ("P/E", "ratio"),
    "peg": ("PEG", "ratio"),
    "price_to_sales": ("Price to sales", "ratio"),
    "price_to_book": ("Price to book", "ratio"),
    "ev_ebitda": ("EV / EBITDA", "ratio"),
    "fcf_yield": ("FCF yield", "pct"),
    "dividend_yield": ("Dividend yield", "pct"),
    "revenue_growth_1y": ("Revenue growth 1y", "pct"),
    "revenue_growth_3y": ("Revenue growth 3y", "pct"),
    "revenue_growth_5y": ("Revenue growth 5y", "pct"),
    "eps_growth_1y": ("EPS growth 1y", "pct"),
    "eps_growth_3y": ("EPS growth 3y", "pct"),
    "eps_growth_5y": ("EPS growth 5y", "pct"),
    "fcf_growth_5y": ("FCF growth 5y", "pct"),
    "shares_growth_5y": ("Share count growth 5y", "pct"),
    "gross_margin": ("Gross margin", "pct"),
    "operating_margin": ("Operating margin", "pct"),
    "net_margin": ("Net margin", "pct"),
    "roe": ("Return on equity", "pct"),
    "roic": ("Return on invested capital", "pct"),
    "cash_conversion": ("Cash conversion", "pct"),
    "debt_to_equity": ("Debt to equity", "ratio"),
    "net_cash_per_share": ("Net cash per share", "price"),
    "net_debt_ebitda": ("Net debt / EBITDA", "times"),
    "current_ratio": ("Current ratio", "ratio"),
    "interest_coverage": ("Interest coverage", "times"),
    "revenue_ttm": ("Revenue, TTM", "money"),
    "net_income_ttm": ("Net income, TTM", "money"),
}
# Shown in every result row, in this order, besides the name columns.
COLUMNS = (
    "lynch_score",
    "market_cap",
    "price",
    "pe",
    "peg",
    "eps_growth_5y",
    "revenue_growth_5y",
    "debt_to_equity",
    "net_margin",
    "roe",
    "fcf_yield",
)
OPS = {"gt", "gte", "lt", "lte", "between"}
MAX_LIMIT = 500
STALE_AFTER = timedelta(days=548)

LYNCH_PRESET = {
    "filters": [
        ["peg", "lt", 1.0],
        ["eps_growth_5y", "gt", 0.15],
        ["debt_to_equity", "lt", 0.5],
        ["market_cap", "between", [3e8, 1e10]],
    ],
    "sort": "lynch_score",
    "dir": "desc",
}


def parse_filter(raw: str) -> tuple[str, str, list[float]]:
    try:
        key, op, value = raw.split(":", 2)
        values = [float(v) for v in value.split(",")]
    except ValueError as exc:
        raise HTTPException(400, f"Bad filter {raw!r}: use metric:op:value") from exc
    if key not in FIELDS:
        raise HTTPException(400, f"Unknown metric {key!r}")
    if op not in OPS or (op == "between") != (len(values) == 2) or len(values) not in (1, 2):
        raise HTTPException(400, f"Bad operator in {raw!r}")
    return key, op, values


def _condition(key: str, op: str, values: list[float]):
    col = getattr(Ratio, key)
    if op == "between":
        lo, hi = sorted(values)
        return and_(col >= lo, col <= hi)
    v = values[0]
    return {"gt": col > v, "gte": col >= v, "lt": col < v, "lte": col <= v}[op]


def run_screen(
    session: Session,
    filters: list[tuple[str, str, list[float]]],
    sectors: list[str],
    categories: list[str],
    sort: str,
    direction: str,
    limit: int,
    offset: int,
) -> dict:
    # Companies whose latest figures are over 18 months old have stopped filing (or moved to
    # forms version 1 does not read); their ratios would mislead a screen.
    conds = [Company.supported.is_(True), Ratio.as_of >= date.today() - STALE_AFTER]
    for key, op, values in filters:
        conds.append(_condition(key, op, values))
    if sectors:
        conds.append(Company.sector.in_(sectors))
    if categories:
        conds.append(Ratio.lynch_category.in_(categories))

    total = session.scalar(
        select(func.count())
        .select_from(Ratio)
        .join(Company, Company.cik == Ratio.cik)
        .where(*conds)
    )
    order_col = getattr(Ratio, sort) if sort in FIELDS else Company.ticker
    order = desc(order_col) if direction == "desc" else asc(order_col)
    keys = list(dict.fromkeys([*COLUMNS, *(f[0] for f in filters)]))
    query = (
        select(
            Company.ticker,
            Company.name,
            Company.sector,
            Company.tier,
            Ratio.lynch_category,
            Quote.change_pct,
            *(getattr(Ratio, k) for k in keys),
        )
        .join(Company, Company.cik == Ratio.cik)
        .outerjoin(Quote, Quote.ticker == Company.ticker)
        .where(*conds)
        .order_by(order_col.is_(None), order, Company.ticker)
        .limit(limit)
        .offset(offset)
    )
    rows = []
    for r in session.execute(query).all():
        ticker, name, sector, tier, category, change_pct, *values = r
        rows.append(
            {
                "ticker": ticker,
                "name": name,
                "sector": sector,
                "tier": tier,
                "category": category,
                "day_change_pct": change_pct,
                **dict(zip(keys, values, strict=True)),
            }
        )
    return {"total": total, "rows": rows, "columns": keys}


@router.get("/screener")
def screener(
    session: DbSession,
    f: Annotated[list[str], Query()] = [],  # noqa: B006
    sector: Annotated[list[str], Query()] = [],  # noqa: B006
    category: Annotated[list[str], Query()] = [],  # noqa: B006
    sort: str = "market_cap",
    dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc",
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    filters = [parse_filter(x) for x in f]
    return run_screen(session, filters, sector, category, sort, dir, limit, offset)


@router.get("/screener/fields")
def fields(session: DbSession) -> dict:
    sectors = session.scalars(
        select(Company.sector)
        .where(Company.sector.is_not(None))
        .distinct()
        .order_by(Company.sector)
    ).all()
    return {
        "fields": [{"key": k, "label": label, "kind": kind} for k, (label, kind) in FIELDS.items()],
        "sectors": list(sectors),
        "categories": [
            "Fast grower",
            "Stalwart",
            "Slow grower",
            "Cyclical",
            "Turnaround",
            "Asset play",
        ],
    }


# ---------------------------------------------------------------- saved screens


class ScreenIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    query: dict


def ensure_preset(session: Session) -> None:
    if session.scalar(select(Screen.id).where(Screen.builtin.is_(True))) is None:
        session.add(
            Screen(
                name="Lynch fast growers",
                query=json.dumps(LYNCH_PRESET),
                builtin=True,
                created_at=utcnow(),
            )
        )
        session.commit()


def screen_json(s: Screen) -> dict:
    return {"id": s.id, "name": s.name, "query": json.loads(s.query), "builtin": s.builtin}


@router.get("/screens")
def list_screens(session: DbSession) -> list[dict]:
    ensure_preset(session)
    rows = session.scalars(select(Screen).order_by(Screen.builtin.desc(), Screen.id)).all()
    return [screen_json(s) for s in rows]


@router.post("/screens", status_code=201)
def save_screen(body: ScreenIn, session: DbSession) -> dict:
    for key, op, values in (tuple(x) for x in body.query.get("filters", [])):
        listed = values if isinstance(values, list) else [values]
        parse_filter(f"{key}:{op}:{','.join(str(v) for v in listed)}")
    s = Screen(name=body.name, query=json.dumps(body.query), builtin=False, created_at=utcnow())
    session.add(s)
    session.commit()
    return screen_json(s)


@router.delete("/screens/{screen_id}")
def delete_screen(screen_id: int, session: DbSession) -> dict:
    s = session.get(Screen, screen_id)
    if s is None:
        raise HTTPException(404, "No such screen")
    if s.builtin:
        raise HTTPException(400, "The built-in preset cannot be deleted")
    session.delete(s)
    session.commit()
    return {"deleted": screen_id}
