"""Rebuild the EDGAR test fixtures from EDGAR's companyfacts API.

    python -m tests.fixtures.build_fixtures

Each fixture is the company's companyfacts JSON trimmed to the tags in the metric map, and gzipped,
so the files stay small enough for the repo. EDGAR data is free to reuse. Rebuilding will move the
"latest fiscal year" forward, so update the expected figures in test_fixtures.py with it.
"""

import gzip
import json
from pathlib import Path

from app.pipeline.tags import ALLOWED_FORMS, all_tags
from app.providers.edgar import Edgar

FIXTURES = Path(__file__).parent / "edgar"
COMPANIES = {
    "AAPL": 320193,
    "MSFT": 789019,
    "NVDA": 1045810,
    "AMZN": 1018724,
    "GOOGL": 1652044,
    "JPM": 19617,
    "WMT": 104169,
    "JNJ": 200406,
    "KO": 21344,
    "PG": 80424,
}


FIELDS = ("start", "end", "val", "accn", "form", "filed")


def trim(companyfacts: dict) -> dict:
    """Keep mapped tags, 10-K and 10-Q facts, and the fields the pipeline reads."""
    keep = all_tags()
    facts: dict = {}
    for taxonomy, tags in companyfacts.get("facts", {}).items():
        for tag, body in tags.items():
            if f"{taxonomy}:{tag}" not in keep:
                continue
            units = {
                unit: [
                    {k: e[k] for k in FIELDS if k in e}
                    for e in entries
                    if e.get("form") in ALLOWED_FORMS
                ]
                for unit, entries in body.get("units", {}).items()
            }
            facts.setdefault(taxonomy, {})[tag] = {"units": units}
    return {"cik": companyfacts["cik"], "entityName": companyfacts["entityName"], "facts": facts}


def main() -> None:
    FIXTURES.mkdir(exist_ok=True)
    edgar = Edgar()
    for ticker, cik in COMPANIES.items():
        data = trim(edgar.companyfacts(cik))
        path = FIXTURES / f"{ticker}.json.gz"
        # mtime=0 keeps the gzip bytes stable, so an unchanged rebuild leaves no git diff.
        path.write_bytes(gzip.compress(json.dumps(data, separators=(",", ":")).encode(), mtime=0))
        print(ticker, path.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
