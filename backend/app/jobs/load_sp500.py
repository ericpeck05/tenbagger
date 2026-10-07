"""Load the S&P 500 from EDGAR's per-company API: companies, filings, facts, and ratios.

    python -m app.jobs.load_sp500            # use downloads cached in the last day
    python -m app.jobs.load_sp500 --refetch  # download everything again
    python -m app.jobs.load_sp500 --only AAPL MSFT

Raw JSON is cached gzipped under data/edgar/ so the pipeline can be re-run without
re-downloading. Two requests per company at 8 per second: about two minutes for 500.
"""

import argparse
import csv
import gzip
import json
import logging
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from app.config import get_settings
from app.db.models import Base
from app.db.session import get_engine, get_session
from app.pipeline.company import store_facts_and_ratios, store_filings, upsert_company
from app.pipeline.tags import merge_companyfacts
from app.providers.edgar import Edgar

DATA = Path(__file__).resolve().parents[1] / "data"
SP500_CSV = DATA / "sp500.csv"
PREDECESSORS_CSV = DATA / "predecessors.csv"
CACHE_MAX_AGE = 24 * 3600

log = logging.getLogger("load_sp500")


def read_sp500() -> dict[int, dict]:
    """CIK -> {"name", "tickers"} from the bundled list. Share classes share a CIK."""
    companies: dict[int, dict] = defaultdict(lambda: {"tickers": []})
    with SP500_CSV.open() as f:
        for row in csv.DictReader(f):
            entry = companies[int(row["cik"])]
            entry["tickers"].append(row["ticker"])
            entry.setdefault("name", _clean_name(row["name"]))
    return dict(companies)


def read_predecessors() -> dict[int, int]:
    """CIK -> the CIK it replaced, for companies whose history is filed under an old CIK."""
    with PREDECESSORS_CSV.open() as f:
        return {int(r["cik"]): int(r["predecessor_cik"]) for r in csv.DictReader(f)}


def _clean_name(name: str) -> str:
    return name.split(" (Class")[0].strip()


def _cache_path(kind: str, cik: int) -> Path:
    return get_settings().data_dir / "edgar" / kind / f"{cik}.json.gz"


def cached_fetch(edgar: Edgar, kind: str, cik: int, refetch: bool) -> dict | None:
    path = _cache_path(kind, cik)
    if not refetch and path.exists() and time.time() - path.stat().st_mtime < CACHE_MAX_AGE:
        return json.loads(gzip.decompress(path.read_bytes()))
    data = edgar.submissions(cik) if kind == "submissions" else edgar.companyfacts(cik)
    if data is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(json.dumps(data).encode()))
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refetch", action="store_true", help="ignore cached downloads")
    parser.add_argument("--only", nargs="*", help="limit to these tickers")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    Base.metadata.create_all(get_engine())
    universe = read_sp500()
    if args.only:
        wanted = {t.upper() for t in args.only}
        universe = {c: e for c, e in universe.items() if wanted & set(e["tickers"])}

    edgar = Edgar()
    started = time.monotonic()
    failures: list[str] = []

    predecessors = read_predecessors()

    def fetch(cik: int) -> tuple[int, dict | None, dict | None]:
        facts = cached_fetch(edgar, "companyfacts", cik, args.refetch)
        if facts is not None and cik in predecessors:
            older = cached_fetch(edgar, "companyfacts", predecessors[cik], args.refetch)
            if older is not None:
                facts = merge_companyfacts(facts, older)
        return cik, cached_fetch(edgar, "submissions", cik, args.refetch), facts

    session = next(get_session())
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(fetch, cik) for cik in universe]
        for done, future in enumerate(as_completed(futures), 1):
            try:
                cik, submissions, companyfacts = future.result()
            except Exception as exc:  # one bad company must not stop the load
                failures.append(f"fetch: {exc}")
                continue
            entry = universe[cik]
            label = entry["tickers"][0]
            if submissions is None or companyfacts is None:
                failures.append(f"{label}: not found on EDGAR")
                continue
            try:
                company = upsert_company(
                    session,
                    cik,
                    submissions,
                    tickers=entry["tickers"],
                    name=entry["name"],
                    in_sp500=True,
                )
                store_filings(session, cik, submissions)
                store_facts_and_ratios(session, company, companyfacts)
                session.commit()
            except Exception as exc:
                session.rollback()
                failures.append(f"{label}: {exc.__class__.__name__}: {exc}")
                log.exception("failed on %s", label)
                continue
            if done % 50 == 0 or done == len(futures):
                log.info(
                    "%d / %d companies (%.0fs)", done, len(futures), time.monotonic() - started
                )

    edgar.close()
    log.info(
        "Loaded %d companies in %.0fs", len(universe) - len(failures), time.monotonic() - started
    )
    for f in failures:
        log.warning("  %s", f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
