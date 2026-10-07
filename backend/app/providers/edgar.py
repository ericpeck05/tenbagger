"""SEC EDGAR adapter: ticker map, company submissions, and XBRL company facts.

Every request sends the User-Agent from `.env`. EDGAR refuses requests without one.
"""

from typing import Any

import httpx

from app.config import get_settings
from app.providers.base import HttpProvider, ProviderError, RateLimiter

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"


_limiter: RateLimiter | None = None


def _shared_limiter(per_second: float) -> RateLimiter:
    """One limiter for every EDGAR client in the process, so jobs running at the same time
    still stay under SEC's limit together."""
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter(per_second, 1.0)
    return _limiter


def pad_cik(cik: int | str) -> str:
    return str(int(cik)).zfill(10)


def filing_url(cik: int | str, accession: str, document: str) -> str:
    return ARCHIVE_URL.format(cik=int(cik), accession=accession.replace("-", ""), document=document)


class Edgar(HttpProvider):
    name = "edgar"

    def __init__(self, transport: httpx.BaseTransport | None = None):
        settings = get_settings()
        user_agent = settings.sec_user_agent.get_secret_value().strip()
        if not user_agent:
            raise ProviderError("SEC_USER_AGENT is not set in .env")
        super().__init__(
            _shared_limiter(settings.edgar_per_second),
            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
            transport=transport,
        )

    def _json(self, url: str) -> Any:
        res = self.get(url)
        if res.status_code == 404:
            return None
        if res.status_code != 200:
            raise ProviderError(f"edgar: HTTP {res.status_code} on {url}")
        return res.json()

    def company_tickers(self) -> list[dict]:
        """All tickers EDGAR knows, as dicts with cik_str, ticker, title."""
        data = self._json(TICKERS_URL) or {}
        return list(data.values())

    def submissions(self, cik: int | str) -> dict | None:
        return self._json(SUBMISSIONS_URL.format(cik=pad_cik(cik)))

    def companyfacts(self, cik: int | str) -> dict | None:
        return self._json(COMPANYFACTS_URL.format(cik=pad_cik(cik)))
