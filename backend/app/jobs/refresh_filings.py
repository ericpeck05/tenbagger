"""Nightly: pick up new filings from EDGAR's daily index and refresh the companies that filed.

    python -m app.jobs.refresh_filings              # every day since the last run
    python -m app.jobs.refresh_filings --since 2026-10-01

For each day since the last run, read `master.YYYYMMDD.idx`. Companies we track that filed a
10-K or 10-Q get their facts and ratios reloaded from the per-company API; an 8-K or Form 4
refreshes the filings list only. EDGAR's companyfacts can lag a filing by days, so a company
whose facts do not yet include a new 10-K or 10-Q is retried on the next runs for a week.
"""

import argparse
import json
import logging
import sys
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Company, FactRow
from app.jobs.load_sp500 import read_predecessors
from app.jobs.runs import get_cursor, recorded, set_cursor
from app.market import now_ny
from app.pipeline.company import store_facts_and_ratios, store_filings, upsert_company
from app.pipeline.tags import merge_companyfacts
from app.providers.base import ProviderError
from app.providers.edgar import Edgar

INDEX_URL = "https://www.sec.gov/Archives/edgar/daily-index/{y}/QTR{q}/master.{d}.idx"
FACT_FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A", "10-KT", "10-QT"}
LIST_FORMS = {"8-K", "8-K/A", "4", "4/A"}
RETRY_DAYS = 7
JOB = "filings"

log = logging.getLogger("refresh_filings")


def parse_index(text: str) -> list[tuple[int, str, date]]:
    """(cik, form, filed) rows from a pipe-delimited master index."""
    rows = []
    body = text.split("\n-----", 1)[-1] if "\n-----" in text else text
    for line in body.splitlines():
        parts = line.split("|")
        if len(parts) != 5 or not parts[0].strip().isdigit():
            continue
        cik, _name, form, filed, _file = parts
        try:
            digits = filed.strip().replace("-", "")
            day = date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
        except ValueError:
            continue
        rows.append((int(cik), form.strip(), day))
    return rows


def fetch_index(edgar: Edgar, day: date) -> list[tuple[int, str, date]] | None:
    """The day's filings, or None if EDGAR has no index for it (weekend, holiday, not yet)."""
    url = INDEX_URL.format(y=day.year, q=(day.month - 1) // 3 + 1, d=day.strftime("%Y%m%d"))
    res = edgar.get(url)
    if res.status_code in (403, 404):
        return None
    if res.status_code != 200:
        raise ProviderError(f"edgar: HTTP {res.status_code} on {url}")
    return parse_index(res.text)


def refresh_company(session: Session, edgar: Edgar, cik: int, facts_too: bool) -> date | None:
    """Reload one company's filings (and facts). Returns the newest fact's filing date."""
    company = session.get(Company, cik)
    if company is None:
        return None
    submissions = edgar.submissions(cik)
    if submissions is None:
        return None
    upsert_company(
        session,
        cik,
        submissions,
        tickers=[company.ticker],
        name=company.name,
        in_sp500=company.in_sp500,
    )
    store_filings(session, cik, submissions)
    if facts_too:
        facts = edgar.companyfacts(cik)
        predecessor = read_predecessors().get(cik)
        if facts is not None and predecessor:
            older = edgar.companyfacts(predecessor)
            if older is not None:
                facts = merge_companyfacts(facts, older)
        if facts is not None:
            store_facts_and_ratios(session, company, facts)
    session.commit()
    return session.scalar(select(func.max(FactRow.filed_at)).where(FactRow.cik == cik))


def run(session: Session, edgar: Edgar, since: date | None = None) -> dict:
    cursor = get_cursor(session, JOB)
    state = json.loads(cursor) if cursor else {}
    last = date.fromisoformat(state["last_day"]) if state.get("last_day") else None
    start = since or (last + timedelta(days=1) if last else now_ny().date() - timedelta(days=1))
    pending: dict[str, str] = state.get("pending", {})  # cik -> filed date still awaited

    tracked = set(session.scalars(select(Company.cik)).all())
    facts_due: dict[int, date] = {int(c): date.fromisoformat(d) for c, d in pending.items()}
    list_due: set[int] = set()
    day, done_through = start, last
    today = now_ny().date()
    while day <= today:
        rows = fetch_index(edgar, day)
        if rows is None:
            if day >= today - timedelta(days=1):
                break  # not posted yet; try again next run
            day += timedelta(days=1)
            continue
        for cik, form, filed in rows:
            if cik not in tracked:
                continue
            if form in FACT_FORMS:
                facts_due[cik] = max(filed, facts_due.get(cik, filed))
            elif form in LIST_FORMS:
                list_due.add(cik)
        done_through = day
        day += timedelta(days=1)

    refreshed = still_waiting = 0
    new_pending: dict[str, str] = {}
    for cik, filed in sorted(facts_due.items()):
        try:
            newest = refresh_company(session, edgar, cik, facts_too=True)
        except ProviderError as exc:
            log.warning("CIK %d: %s", cik, exc)
            newest = None
        refreshed += 1
        if (newest is None or newest < filed) and filed >= today - timedelta(days=RETRY_DAYS):
            new_pending[str(cik)] = filed.isoformat()
            still_waiting += 1
    for cik in sorted(list_due - set(facts_due)):
        try:
            refresh_company(session, edgar, cik, facts_too=False)
        except ProviderError as exc:
            log.warning("CIK %d: %s", cik, exc)

    set_cursor(
        session,
        JOB,
        json.dumps(
            {"last_day": done_through.isoformat() if done_through else None, "pending": new_pending}
        ),
    )
    return {
        "through": done_through.isoformat() if done_through else None,
        "facts_refreshed": refreshed,
        "filings_refreshed": len(list_due - set(facts_due)),
        "awaiting_companyfacts": still_waiting,
    }


def filings_job(since: date | None = None) -> dict:
    from app.db.session import session_scope

    edgar = Edgar()
    try:
        with session_scope() as session, recorded(session, JOB) as detail:
            detail.update(run(session, edgar, since))
            return detail
    finally:
        edgar.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", type=date.fromisoformat)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    log.info("%s", filings_job(args.since))
    return 0


if __name__ == "__main__":
    sys.exit(main())
