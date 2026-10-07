"""Save trimmed EDGAR submissions JSON for the demo companies (run once; the output is
committed). EDGAR data is free to reuse; only the fields the app reads are kept.

    python -m app.demo.fetch_submissions
"""

import gzip
import json
from pathlib import Path

from app.pipeline.company import FILING_FORMS
from app.providers.edgar import Edgar
from tests.fixtures.build_fixtures import COMPANIES

OUT = Path(__file__).parent / "submissions"
KEEP = ("cik", "name", "sic", "sicDescription", "tickers", "exchanges", "fiscalYearEnd")
COLUMNS = ("accessionNumber", "form", "filingDate", "reportDate", "primaryDocument", "items")
PER_FORM = 6  # the latest few of each form is enough for the filings panels


def trim(sub: dict) -> dict:
    recent = sub["filings"]["recent"]
    rows = list(zip(*(recent[c] for c in COLUMNS), strict=False))
    kept, counts = [], {}
    for row in rows:
        form = row[1]
        if form in FILING_FORMS and counts.get(form, 0) < PER_FORM:
            kept.append(row)
            counts[form] = counts.get(form, 0) + 1
    return {
        **{k: sub.get(k) for k in KEEP},
        "filings": {"recent": {c: [r[i] for r in kept] for i, c in enumerate(COLUMNS)}},
    }


def main() -> None:
    OUT.mkdir(exist_ok=True)
    edgar = Edgar()
    for ticker, cik in COMPANIES.items():
        data = trim(edgar.submissions(cik))
        path = OUT / f"{ticker}.json.gz"
        path.write_bytes(gzip.compress(json.dumps(data, separators=(",", ":")).encode(), mtime=0))
        print(ticker, path.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
