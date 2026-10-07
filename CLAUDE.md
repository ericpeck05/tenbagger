# Tenbagger

A local stock research and portfolio tracking app built on free data. Python backend, React frontend, SQLite. Runs on the owner's Mac, code is public on GitHub.

`SPEC.md` is the source of truth. Read it fully before writing code. When the spec and this file disagree, ask.

## How to work

- Build one phase from the "Build phases" table in `SPEC.md` at a time. Do not start the next phase until the owner has reviewed the current one.
- A phase is done only when its "Done when" test passes. Run the tests and open the app in a browser to check before saying it is done.
- At the end of each phase, report: what was built, how it was verified, anything that differs from the spec, and anything that needs a decision.
- If something in the spec turns out to be wrong or impossible on the free data sources, stop and say so. Do not quietly work around it.
- Update `SPEC.md` in the same pull request whenever a decision changes.

## Commands

Phase 0 creates these. Keep them working.

- `make dev` starts the backend and frontend and opens `http://localhost:5173`
- `make test` runs `pytest` and the frontend type check
- `make lint` runs `ruff` and the frontend linter
- `make demo` runs the app on bundled sample data with no keys (phase 7)

## Hard rules

- **Secrets.** Keys live only in `.env`, which is gitignored. Never print, log, or commit a key. Never write the owner's email into code. It goes in `.env` as `SEC_USER_AGENT`.
- **Data in the repo.** Never commit anything fetched from Finnhub or Alpaca, the database, or downloaded archives. Test fixtures are EDGAR JSON only.
- **Portfolio data is private.** The owner's trades never leave the local database. Tests and demo mode use made-up holdings.
- **No fetching while the user waits for fundamentals.** Pages read from the database. Only quotes and price bars for cold stocks are fetched on request.
- **Rate limits.** Every provider call goes through its rate limiter. EDGAR requests always send the `User-Agent` from `.env`.
- **Missing is null.** A ratio with a missing input is stored as null and shown as a dash. Never substitute zero.
- **Test the pipeline.** Tag mapping, TTM, ratio formulas, and portfolio math each have tests. The 10-company fixture tests are the acceptance gate.

## Design

- `design/` holds the mockup sources for the stock page, search, and portfolio. See `design/README.md` for how to read them.
- Copy layout, spacing, type, and color from the mockups. Do not copy their numbers or company names, which are made up.
- True black background, amber accent `#FFA31A`, square corners, uppercase monospace panel title bars, numbered panels with number-key jumps. No blue anywhere, including links, focus rings, and chart defaults.
- IBM Plex Mono for everything except company names and row labels, which use IBM Plex Sans.
- The price chart is the centerpiece: full width, about 500 px tall, candlesticks by default with a line switch.
- Every gain or loss shows a plus or minus sign as well as a color.

## Git

- Repo: `github.com/ericpeck05/tenbagger`, public, MIT license.
- Creating the GitHub repo and the first push are public actions. Confirm with the owner right before doing them.
- One branch and one pull request per phase. Small commits with plain messages.
- Check `git status` for stray files before every commit. If a secret is ever committed, stop and tell the owner at once.
