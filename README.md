# Tenbagger

A local stock research app that opens any US stock in under a second and shows every key ratio on one screen, built entirely on free data. Fundamentals come from SEC EDGAR filings and live in a local SQLite database, so the only live call when a stock opens is its price. It also tracks a personal portfolio, Peter Lynch style.

> Work in progress. See [SPEC.md](SPEC.md) for the full design and build phases.

**This is a research tool, not investment advice.**

## Quick start

Needs Python 3.12+, Node 20+, and `gitleaks` (`brew install gitleaks`).

1. `cp .env.example .env` and set `SEC_USER_AGENT` to your name and contact email. Finnhub and Alpaca keys are free and needed from phase 2.
2. `make setup`
3. `make dev`, which opens http://localhost:5173

Other commands: `make test`, `make lint`.

## Data sources

| Job | Provider | Limit |
| --- | --- | --- |
| Fundamentals and filings | SEC EDGAR APIs | 10 requests per second, User-Agent with contact email required |
| Daily price history | Alpaca Basic (IEX feed) | 200 calls per minute |
| Current quote | Finnhub free tier | about 60 calls per minute |

Finnhub and Alpaca data are for personal use and are never committed to this repo.

## License

MIT
