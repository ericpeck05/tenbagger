"""Load every listed US company from EDGAR's nightly bulk files.

    python -m app.jobs.bulk_load            # download if newer, load, delete the zips
    python -m app.jobs.bulk_load --keep     # keep the zips in data/edgar/bulk for re-runs
    python -m app.jobs.bulk_load --limit 50 # a quick trial on the first 50 companies

`companyfacts.zip` and `submissions.zip` hold the same JSON as the per-company APIs for every
filer, rebuilt each night around 3 a.m. New York time. They are read one company at a time
straight out of the zip, never unzipped to disk. Only companies with a ticker in EDGAR's
ticker list are loaded; S&P 500 names keep their bundled names and stay warm, everyone else
joins the cold tier (a company already warm stays warm).
"""

import argparse
import json
import logging
import re
import sys
import time
import zipfile
from collections import defaultdict
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

from app.config import get_settings
from app.db.session import get_engine, migrate, session_scope
from app.jobs.load_sp500 import read_predecessors, read_sp500
from app.pipeline.company import process_company
from app.pipeline.tags import merge_companyfacts
from app.providers.edgar import Edgar

FACTS_URL = "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"
SUBMISSIONS_URL = "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"
COMMIT_EVERY = 50

log = logging.getLogger("bulk_load")

# Words kept in capitals when tidying an all-caps EDGAR name.
_KEEP_UPPER = {
    "LLC",
    "LP",
    "LLP",
    "PLC",
    "NV",
    "SA",
    "AG",
    "SE",
    "USA",
    "US",
    "II",
    "III",
    "IV",
    "REIT",
    "ETF",
    "AB",
    "ASA",
    "NA",
    "BDC",
    "SPAC",
    "HK",
    "UK",
    "AI",
}


# Vowel-less abbreviations that read as words, so they are capitalized rather than kept upper.
_ABBREVIATIONS = {
    "LTD",
    "MFG",
    "BHD",
    "INTL",
    "SYS",
    "SVCS",
    "GRP",
    "HLDGS",
    "TR",
    "TRS",
    "FD",
    "FDS",
    "CTRS",
    "BLDG",
    "PPTYS",
    "PRTNRS",
    "ST",
    "PHRM",
    "TCH",
    "TKY",
}


def tidy_name(name: str) -> str:
    """Tidy an EDGAR name: "ACME UNITED CORP /DE/" -> "Acme United Corp".

    EDGAR appends the state of incorporation to some names ("/DE/", "/ok/"); it is dropped.
    Mixed-case names keep their case.
    """
    name = re.sub(r"\s*/[A-Za-z]{2,4}/?\s*$", "", name).strip()
    if not name.isupper():
        return name
    words = []
    for w in name.split():
        core = w.strip(".,/()")
        # Keep acronyms: known ones, anything with "&" (S&P, AT&T), and short vowel-less
        # words (SPDR, CVS).
        acronym = core not in _ABBREVIATIONS and (
            core in _KEEP_UPPER or "&" in core or (len(core) <= 5 and not set(core) & set("AEIOUY"))
        )
        words.append(w if acronym else w.capitalize())
    return " ".join(words)


def download(edgar: Edgar, url: str, dest: Path) -> Path:
    """Download `url` to `dest` unless the local copy is already as new as EDGAR's."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    edgar.limiter.wait()
    head = edgar.client.head(url)
    head.raise_for_status()
    remote = parsedate_to_datetime(head.headers["last-modified"])
    if dest.exists() and datetime.fromtimestamp(dest.stat().st_mtime, UTC) >= remote:
        log.info("%s is current (%s)", dest.name, remote.date())
        return dest
    size = int(head.headers.get("content-length", 0))
    log.info("downloading %s (%.2f GB)", dest.name, size / 1e9)
    part = dest.with_suffix(".part")
    started, done, next_report = time.monotonic(), 0, 0.0
    edgar.limiter.wait()
    with edgar.client.stream("GET", url) as res, part.open("wb") as out:
        res.raise_for_status()
        for chunk in res.iter_bytes(1 << 20):
            out.write(chunk)
            done += len(chunk)
            if size and done / size >= next_report:
                log.info("  %s %3.0f%%", dest.name, 100 * done / size)
                next_report += 0.1
    part.replace(dest)
    log.info("  %s done in %.0fs", dest.name, time.monotonic() - started)
    return dest


def ticker_universe(edgar: Edgar) -> tuple[dict[int, list[str]], dict[int, str]]:
    """CIK -> tickers (in our dotted form) and CIK -> name, from EDGAR's ticker list."""
    tickers: dict[int, list[str]] = defaultdict(list)
    names: dict[int, str] = {}
    for row in edgar.company_tickers():
        cik = int(row["cik_str"])
        tickers[cik].append(row["ticker"].upper().replace("-", "."))
        names.setdefault(cik, row["title"])
    return dict(tickers), names


def _read(zf: zipfile.ZipFile, cik: int) -> dict | None:
    try:
        return json.loads(zf.read(f"CIK{cik:010d}.json"))
    except KeyError:
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--keep", action="store_true", help="keep the downloaded zips")
    parser.add_argument("--limit", type=int, help="load only the first N companies")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    migrate(get_engine())
    bulk_dir = get_settings().data_dir / "edgar" / "bulk"
    edgar = Edgar()
    facts_zip = download(edgar, FACTS_URL, bulk_dir / "companyfacts.zip")
    subs_zip = download(edgar, SUBMISSIONS_URL, bulk_dir / "submissions.zip")

    tickers, names = ticker_universe(edgar)
    sp500 = read_sp500()
    predecessors = read_predecessors()
    for cik, entry in sp500.items():  # bundled S&P tickers first, then any others EDGAR lists
        tickers[cik] = entry["tickers"] + [
            t for t in tickers.get(cik, []) if t not in entry["tickers"]
        ]
    ciks = sorted(tickers)
    if args.limit:
        ciks = ciks[: args.limit]
    log.info("loading %d companies", len(ciks))

    started = time.monotonic()
    loaded = no_facts = missing = failed = 0
    with (
        zipfile.ZipFile(facts_zip) as fz,
        zipfile.ZipFile(subs_zip) as sz,
        session_scope() as session,
    ):
        for i, cik in enumerate(ciks, 1):
            submissions = _read(sz, cik)
            if submissions is None:
                missing += 1
                continue
            facts = _read(fz, cik)
            if facts is not None and cik in predecessors:
                older = _read(fz, predecessors[cik])
                if older is not None:
                    facts = merge_companyfacts(facts, older)
            sp = sp500.get(cik)
            try:
                process_company(
                    session,
                    cik,
                    submissions,
                    facts,
                    tickers=tickers[cik],
                    name=sp["name"] if sp else tidy_name(submissions.get("name") or names[cik]),
                    in_sp500=sp is not None,
                )
            except Exception:
                session.rollback()
                failed += 1
                log.exception("failed on CIK %d", cik)
                continue
            loaded += 1
            no_facts += facts is None
            if i % COMMIT_EVERY == 0:
                session.commit()
            if i % 500 == 0:
                rate = i / (time.monotonic() - started)
                log.info("%d / %d companies (%.0f/s)", i, len(ciks), rate)
        session.commit()

    log.info(
        "Loaded %d companies in %.0fs (%d without XBRL facts, %d not in the bulk file, %d failed)",
        loaded,
        time.monotonic() - started,
        no_facts,
        missing,
        failed,
    )
    if not args.keep:
        for z in (facts_zip, subs_zip):
            z.unlink(missing_ok=True)
        log.info("deleted the downloaded zips (pass --keep to keep them)")
    edgar.close()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
