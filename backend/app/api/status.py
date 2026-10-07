from datetime import UTC, datetime

from fastapi import APIRouter
from sqlalchemy import func, select, text

from app import __version__, market
from app.config import get_settings
from app.db.models import Base, Company, FactRow, JobRun, PriceDaily, Quote, Ratio
from app.db.session import get_engine

router = APIRouter()


@router.get("/status")
def status() -> dict:
    settings = get_settings()
    engine = get_engine()
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        db_ok = conn.execute(text("select 1")).scalar() == 1
        tiers = dict(conn.execute(select(Company.tier, func.count()).group_by(Company.tier)).all())
        counts = {
            "companies": conn.execute(select(func.count()).select_from(Company)).scalar(),
            "facts": conn.execute(select(func.count()).select_from(FactRow)).scalar(),
            "ratios": conn.execute(select(func.count()).select_from(Ratio)).scalar(),
        }
        last_load = conn.execute(select(func.max(Company.facts_fetched_at))).scalar()
        counts["quotes"] = conn.execute(select(func.count()).select_from(Quote)).scalar()
        counts["price_bars"] = conn.execute(select(func.count()).select_from(PriceDaily)).scalar()
        runs = conn.execute(select(JobRun)).all()
        newest_quote, oldest_quote = conn.execute(
            select(func.max(Quote.fetched_at), func.min(Quote.fetched_at))
        ).one()
    return {
        "version": __version__,
        "now": datetime.now(UTC).isoformat(),
        "database": {"ok": db_ok, **counts},
        "keys": settings.keys_present(),
        "market": {"open": market.is_open()},
        "jobs": {
            "fundamentals_loaded_at": _iso(last_load),
            "newest_quote_at": _iso(newest_quote),
            "oldest_quote_at": _iso(oldest_quote),
            "runs": {
                r.name: {
                    "started_at": _iso(r.started_at),
                    "finished_at": _iso(r.finished_at),
                    "ok": r.ok,
                    "detail": r.detail,
                }
                for r in runs
            },
        },
        "tiers": tiers,
    }


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None
