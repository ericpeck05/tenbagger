"""Recompute every company's ratios, 5-year history, and Lynch check from the facts already
in the database. No downloads: use it after a change to the formulas or the Lynch rules.

    python -m app.jobs.rescore
    python -m app.jobs.rescore --only AAPL MSFT
"""

import argparse
import logging
import sys
import time
from collections import defaultdict

from sqlalchemy import func, select

from app.db.models import Company, FactRow, Ticker
from app.db.session import get_engine, migrate, session_scope
from app.pipeline.company import compute_ratios
from app.pipeline.tags import ALLOWED_FORMS, Fact

log = logging.getLogger("rescore")


def facts_for(session, cik: int) -> tuple[dict, tuple | None]:
    facts: dict[str, dict[tuple, Fact]] = defaultdict(dict)
    latest = None
    for r in session.scalars(select(FactRow).where(FactRow.cik == cik)).all():
        f = Fact(
            r.metric,
            r.period_start,
            r.period_end,
            r.value,
            r.form,
            r.filed_at,
            r.accession,
            r.source_tag,
        )
        facts[r.metric][f.period] = f
        if r.form in ALLOWED_FORMS and (latest is None or r.filed_at > latest[0]):
            latest = (r.filed_at, r.form)
    return dict(facts), latest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", nargs="*")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    migrate(get_engine())
    started = time.monotonic()
    with session_scope() as session:
        query = select(FactRow.cik).group_by(FactRow.cik).having(func.count() > 0)
        if args.only:
            query = select(Ticker.cik).where(Ticker.ticker.in_([t.upper() for t in args.only]))
        ciks = sorted(set(session.scalars(query).all()))
        for i, cik in enumerate(ciks, 1):
            company = session.get(Company, cik)
            if company is None or not company.supported:
                continue
            facts, latest = facts_for(session, cik)
            if facts:
                compute_ratios(session, company, facts, latest)
            if i % 100 == 0:
                session.commit()
            if i % 1000 == 0:
                log.info("%d / %d companies", i, len(ciks))
        session.commit()
    log.info("Rescored %d companies in %.0fs", len(ciks), time.monotonic() - started)
    return 0


if __name__ == "__main__":
    sys.exit(main())
