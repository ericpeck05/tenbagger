"""Nightly promotion and demotion between the warm and cold tiers.

Warm: the S&P 500, the watchlist, every holding, and any company opened 3 times in 30 days.
Demoted: anything not in those groups that has not been opened for 90 days.
"""

from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db.models import Company, CompanyView, Ticker, WatchItem
from app.jobs.runs import recorded
from app.pipeline import holdings
from app.pipeline.pricing import utcnow

PROMOTE_VIEWS = 3
PROMOTE_WINDOW = timedelta(days=30)
DEMOTE_AFTER = timedelta(days=90)


def _ciks_for(session: Session, tickers: list[str]) -> set[int]:
    if not tickers:
        return set()
    return set(session.scalars(select(Ticker.cik).where(Ticker.ticker.in_(tickers))).all())


def protected(session: Session) -> set[int]:
    """Companies that are always warm."""
    sp = set(session.scalars(select(Company.cik).where(Company.in_sp500.is_(True))).all())
    watch = _ciks_for(session, list(session.scalars(select(WatchItem.ticker)).all()))
    held = _ciks_for(session, holdings.held_tickers(session))
    return sp | watch | held


def run(session: Session) -> dict:
    now = utcnow()
    keep = protected(session)
    busy = set(
        session.scalars(
            select(CompanyView.cik)
            .where(CompanyView.viewed_at >= now - PROMOTE_WINDOW)
            .group_by(CompanyView.cik)
            .having(func.count() >= PROMOTE_VIEWS)
        ).all()
    )
    to_warm = (keep | busy) - set(
        session.scalars(select(Company.cik).where(Company.tier == "warm")).all()
    )
    if to_warm:
        session.execute(update(Company).where(Company.cik.in_(to_warm)).values(tier="warm"))

    stale = set(
        session.scalars(
            select(Company.cik).where(
                Company.tier == "warm",
                (Company.last_viewed_at.is_(None)) | (Company.last_viewed_at < now - DEMOTE_AFTER),
            )
        ).all()
    )
    to_cold = stale - keep - busy
    if to_cold:
        session.execute(update(Company).where(Company.cik.in_(to_cold)).values(tier="cold"))

    # Views older than the window are no longer needed.
    session.execute(
        CompanyView.__table__.delete().where(CompanyView.viewed_at < now - PROMOTE_WINDOW)
    )
    session.commit()
    return {"promoted": len(to_warm), "demoted": len(to_cold)}


def tiers_job() -> dict:
    from app.db.session import session_scope

    with session_scope() as session, recorded(session, "tiers") as detail:
        detail.update(run(session))
        return detail
