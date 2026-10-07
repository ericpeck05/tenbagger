"""Read Form 4 filings for open-market insider buys and sales.

    python -m app.jobs.insiders            # every warm company
    python -m app.jobs.insiders --only AAPL

Each Form 4 in the last six months is fetched once (as raw XML, from the same folder as the
rendered page the filings list links to). Transaction code P is an open-market purchase and
S an open-market sale; grants, option exercises, and gifts are ignored. A filing counts once
as a buy or a sale however many lots it lists. Counts are stored on the ratios row only when
every Form 4 in the window has been read, so a half-read company shows the test as missing.
"""

import argparse
import logging
import re
import sys
import threading
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Company, Filing, Form4Parsed, InsiderTrade, Ratio, Ticker
from app.jobs.runs import recorded
from app.pipeline.lynch_config import INSIDER_WINDOW_DAYS
from app.pipeline.pricing import utcnow
from app.pipeline.scoring import refresh_lynch
from app.providers.base import ProviderError
from app.providers.edgar import Edgar

log = logging.getLogger("insiders")
FORMS = ("4", "4/A")


def raw_xml_url(url: str) -> str:
    """The filings list links to EDGAR's rendered view; the XML sits one folder up."""
    return re.sub(r"/xslF345X\d+/", "/", url)


def _text(node: ET.Element | None, path: str) -> str | None:
    if node is None:
        return None
    found = node.find(path)
    return found.text.strip() if found is not None and found.text else None


def _num(s: str | None) -> float | None:
    try:
        return float(s) if s not in (None, "") else None
    except ValueError:
        return None


def role_of(owner: ET.Element | None) -> str:
    rel = owner.find("reportingOwnerRelationship") if owner is not None else None
    if rel is None:
        return "Insider"

    def yes(tag: str) -> bool:
        return (_text(rel, tag) or "").lower() in ("1", "true")

    if yes("isOfficer"):
        title = _text(rel, "officerTitle")
        return title.title() if title and title.isupper() else (title or "Officer")
    if yes("isDirector"):
        return "Director"
    if yes("isTenPercentOwner"):
        return "10% owner"
    return "Insider"


def parse_form4(xml: str) -> list[dict]:
    """Open-market buys and sales in one Form 4."""
    root = ET.fromstring(xml)
    owner = root.find("reportingOwner")
    person = _text(owner, "reportingOwnerId/rptOwnerName")
    role = role_of(owner)
    out = []
    for tx in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        code = _text(tx, "transactionCoding/transactionCode")
        if code not in ("P", "S"):
            continue
        day = _text(tx, "transactionDate/value")
        out.append(
            {
                "code": code,
                "person": person,
                "role": role,
                "shares": _num(_text(tx, "transactionAmounts/transactionShares/value")),
                "price": _num(_text(tx, "transactionAmounts/transactionPricePerShare/value")),
                "trade_date": date.fromisoformat(day[:10]) if day else None,
            }
        )
    return out


def title_for(trades: list[dict]) -> str | None:
    """ "Director bought 12,000 shares" for a filing with open-market trades."""
    if not trades:
        return None
    buys = sum(t["shares"] or 0 for t in trades if t["code"] == "P")
    sells = sum(t["shares"] or 0 for t in trades if t["code"] == "S")
    role = trades[0]["role"]
    if buys and not sells:
        return f"{role} bought {buys:,.0f} shares"
    if sells and not buys:
        return f"{role} sold {sells:,.0f} shares"
    return f"{role} bought {buys:,.0f} and sold {sells:,.0f} shares"


def update_counts(session: Session, cik: int, today: date | None = None) -> tuple[int, int] | None:
    """Store 6-month buy and sell counts on the ratios row, if every Form 4 has been read."""
    since = (today or date.today()) - timedelta(days=INSIDER_WINDOW_DAYS)
    filings = session.scalars(
        select(Filing.accession).where(
            Filing.cik == cik, Filing.form.in_(FORMS), Filing.filed_at >= since
        )
    ).all()
    parsed = set(session.scalars(select(Form4Parsed.accession).where(Form4Parsed.cik == cik)).all())
    row = session.get(Ratio, cik)
    if row is None:
        return None
    if not set(filings) <= parsed:
        row.insider_buys_6m = row.insider_sells_6m = None
        return None
    codes: dict[str, set[str]] = {}
    for acc, code in session.execute(
        select(InsiderTrade.accession, InsiderTrade.code).where(
            InsiderTrade.cik == cik, InsiderTrade.filed_at >= since
        )
    ).all():
        codes.setdefault(acc, set()).add(code)
    buys = sum(1 for c in codes.values() if "P" in c)
    sells = sum(1 for c in codes.values() if "S" in c)
    row.insider_buys_6m, row.insider_sells_6m = float(buys), float(sells)
    refresh_lynch(session, row)
    return buys, sells


def refresh_company(session: Session, edgar: Edgar, cik: int) -> int:
    """Read any unread Form 4s in the window for one company. Returns filings read."""
    since = date.today() - timedelta(days=INSIDER_WINDOW_DAYS)
    parsed = set(session.scalars(select(Form4Parsed.accession).where(Form4Parsed.cik == cik)).all())
    todo = [
        f
        for f in session.scalars(
            select(Filing).where(
                Filing.cik == cik, Filing.form.in_(FORMS), Filing.filed_at >= since
            )
        ).all()
        if f.accession not in parsed
    ]
    for f in todo:
        try:
            res = edgar.get(raw_xml_url(f.url))
            trades = parse_form4(res.text) if res.status_code == 200 else []
        except (ProviderError, ET.ParseError) as exc:
            log.warning("CIK %d %s: %s", cik, f.accession, exc)
            continue
        for t in trades:
            session.add(InsiderTrade(cik=cik, accession=f.accession, filed_at=f.filed_at, **t))
        title = title_for(trades)
        if title:
            f.title = title
        session.add(Form4Parsed(cik=cik, accession=f.accession, parsed_at=utcnow()))
    update_counts(session, cik)
    session.commit()
    return len(todo)


_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="insiders")
_queued: set[int] = set()
_lock = threading.Lock()


def refresh_soon(cik: int) -> None:
    """Read a company's Form 4s in the background (used when a cold stock is opened)."""
    from app.db.session import session_scope

    with _lock:
        if cik in _queued:
            return
        _queued.add(cik)

    def run() -> None:
        try:
            edgar = Edgar()
            with session_scope() as session:
                refresh_company(session, edgar, cik)
        except ProviderError as exc:
            log.warning("insiders for CIK %d: %s", cik, exc)
        finally:
            with _lock:
                _queued.discard(cik)

    _pool.submit(run)


def insiders_job(only: list[str] | None = None) -> dict:
    from app.db.session import session_scope

    edgar = Edgar()
    with session_scope() as session, recorded(session, "insiders") as detail:
        query = select(Company.cik).where(Company.tier == "warm")
        if only:
            query = select(Ticker.cik).where(Ticker.ticker.in_([t.upper() for t in only]))
        ciks = sorted(set(session.scalars(query).all()))
        read = 0
        for i, cik in enumerate(ciks, 1):
            read += refresh_company(session, edgar, cik)
            if i % 50 == 0:
                log.info("insiders: %d / %d companies, %d filings read", i, len(ciks), read)
        detail.update(companies=len(ciks), filings_read=read)
        return detail


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", nargs="*")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    log.info("%s", insiders_job(args.only))
    return 0


if __name__ == "__main__":
    sys.exit(main())
