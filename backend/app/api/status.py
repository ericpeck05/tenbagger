from datetime import UTC, datetime

from fastapi import APIRouter
from sqlalchemy import func, select, text

from app import __version__
from app.config import get_settings
from app.db.models import Base, Company, FactRow, Ratio
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
    return {
        "version": __version__,
        "now": datetime.now(UTC).isoformat(),
        "database": {"ok": db_ok, **counts},
        "keys": settings.keys_present(),
        "jobs": {"fundamentals_loaded_at": last_load.isoformat() if last_load else None},
        "tiers": tiers,
    }
