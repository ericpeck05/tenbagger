from datetime import UTC, datetime

from fastapi import APIRouter
from sqlalchemy import text

from app import __version__
from app.config import get_settings
from app.db.session import get_engine

router = APIRouter()


@router.get("/status")
def status() -> dict:
    settings = get_settings()
    with get_engine().connect() as conn:
        db_ok = conn.execute(text("select 1")).scalar() == 1
    return {
        "version": __version__,
        "now": datetime.now(UTC).isoformat(),
        "database": {"ok": db_ok},
        "keys": settings.keys_present(),
        "jobs": {},
        "tiers": {},
    }
