# Tenbagger: Build Spec

Version of 2026-10-06. Owner: Eric Peck (GitHub `ericpeck05`).

## Summary

Tenbagger is a local stock research app that opens any US stock in under a second and shows every key ratio on one screen, built entirely on free data. It also tracks the owner's portfolio. "Tenbagger" is a working title.

The previous screener was slow because it fetched data from yfinance while the user waited. This build never does that. Fundamentals for the whole market sit in a local database, and the only live call when a stock opens is its price.

Decisions already made:

- **Cost:** free data sources only. No paid API.
- **Where it runs:** on the owner's Mac mini, opened in the browser at a local address.
- **Code:** a public GitHub repo, written to be read by other people.
- **Loading:** S&P 500 companies, holdings, and the watchlist stay warm. Everything else gets its price on request.
- **Framework:** Peter Lynch style. PEG, growth, balance sheet strength, and the six Lynch categories are first-class.

Out of scope for the first version: social features, user accounts, hosting for other people, analyst estimates, and forward P/E.

## Data sources

Three free providers cover everything, and each does one job. Every provider sits behind a small adapter so it can be swapped without touching the rest of the app.

| Job | Provider | What it gives | Limit | Key needed |
| --- | --- | --- | --- | --- |
| Fundamentals and filings | [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) | Every reported XBRL fact per company, filing history, ticker to CIK map | [10 requests per second](https://www.sec.gov/about/webmaster-frequently-asked-questions) | No, but a User-Agent with a contact email is required |
| Daily price history | [Alpaca Basic plan](https://docs.alpaca.markets/docs/about-market-data-api) | Daily bars since January 2016, consolidated SIP feed | 200 calls per minute (confirmed), SIP requests must end at least 15 minutes ago | Yes, free account |
| Current quote | [Finnhub free tier](https://finnhub.io/docs/api) | Latest price and day change for US stocks | 60 calls per minute (confirmed 2026-10-07) | Yes, free account |

Notes that shape the build:

- **EDGAR endpoints.** `https://data.sec.gov/submissions/CIK##########.json` (filing history and company metadata), `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` (all facts for one company), `https://www.sec.gov/files/company_tickers.json` (ticker to CIK map). CIKs are 10 digits, zero padded.
- **EDGAR headers.** Every request needs `User-Agent: <name> <contact email>`. Requests without it get a 403.
- **EDGAR bulk file.** `https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip` holds the same data as the per-company API for every filer and is rebuilt nightly at about 3:00 a.m. ET. `https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip` does the same for filing history. The whole-market load uses these instead of thousands of single calls.
- **EDGAR freshness.** The XBRL APIs update within about a minute of a filing being published, so new quarters arrive when the 10-Q or 10-K posts, not when earnings are announced.
- **EDGAR and the browser.** `data.sec.gov` does not support CORS. A web page cannot call it directly, which is why this app needs a backend.
- **Alpaca.** Base URL `https://data.alpaca.markets`, headers `APCA-API-KEY-ID` and `APCA-API-SECRET-KEY`. Request split-adjusted bars from the `sip` feed with an end time at least 15 minutes ago: on the free plan that returns market-wide bars back to January 2016. (Tested 2026-10-07. The `iex` feed, which the spec first named, only goes back to July 2020 and covers one exchange.) Bars are fetched through the latest finished session only, so a partial day is never stored as a close; today's candle comes from the live quote. Volume is still not shown.
- **Finnhub.** The free key's limit is 60 calls per minute, confirmed from the `x-ratelimit-limit` header on the first call. The config runs at 50. The limiter is a token bucket that holds 5 calls; the background quote loop always leaves 3 of them free, so a stock opened by hand never queues behind the loop. Do not rely on Finnhub for price history. Free keys have been reported as denied on the candles endpoint.
- **Reuse.** SEC states that EDGAR filing content is free to access and reuse. Finnhub and Alpaca free plans are for personal use, so their data stays on the owner's machine and never goes into the repo.

## Architecture

A small Python backend owns all data fetching and a local SQLite file. The browser talks only to that backend, and only ever reads the local database.

```
            Browser UI (React app at localhost)
                        |
                        |  JSON over localhost
                        v
  +--------------------- runs on the Mac ----------------------+
  |                                                            |
  |   API server  --reads-->  SQLite database  <--writes--  Fetcher
  |   (FastAPI)                                      (rate-limited adapters)
  |        |                                              ^    |
  |        +------------- on a cache miss ----------------+    |
  +------------------------------------------------------------+
                                                          |
                 +----------------------+-----------------+
                 v                      v                 v
            SEC EDGAR                 Alpaca           Finnhub
     fundamentals and filings    daily price bars   current quotes
```

The page never waits on a provider for fundamentals. On a cache miss the API asks the fetcher for a quote and price bars, stores them, and answers.

**Stack**

- **Backend:** Python 3.12 or newer, FastAPI, `httpx` for requests, APScheduler for background jobs, SQLite through SQLAlchemy.
- **Frontend:** React, TypeScript, Vite, TanStack Query for caching, [Lightweight Charts](https://github.com/tradingview/lightweight-charts) for the price chart.
- **Run:** one command, `make dev`, starts both and opens `http://localhost:5173`.

**Repo layout**

```
tenbagger/
  backend/
    app/
      api/          routes: stock, search, screener, watchlist, portfolio, transactions
      providers/    edgar.py, alpaca.py, finnhub.py, base.py
      pipeline/     tags.py, ttm.py, ratios.py, lynch.py, sector.py, portfolio.py
      jobs/         bulk_load.py, refresh_filings.py, quotes_loop.py
      db/           models.py, session.py
    tests/          fixtures of saved EDGAR JSON, ratio tests, portfolio tests
  frontend/
    src/            pages, components, api client, tokens.css
  design/           mockup sources, reference only
  data/             tenbagger.db and downloads, gitignored
  .env.example
  README.md
```

Rules for the fetcher:

- One rate limiter per provider, with the limit read from config. Stay under the limit, not at it: 8 per second for EDGAR, 50 per minute for Finnhub, 150 per minute for Alpaca.
- Back off and retry on HTTP 429 and 5xx. Never fail a page because a provider is down. Serve the cached value with its age.
- Every stored value carries the time it was fetched, so the UI can show how old it is.

## Data model

One SQLite file, `data/tenbagger.db`. Ratios are stored, not computed per request, so the screener is a single query.

| Table | One row per | Key columns |
| --- | --- | --- |
| `companies` | Company | `cik`, `ticker` (primary), `name`, `exchange`, `sic_code`, `sector`, `fiscal_year_end`, `tier`, `in_sp500`, `supported`, `view_count`, `last_viewed_at`, `facts_fetched_at` |
| `tickers` | Ticker | `ticker`, `cik`, `is_primary`. Multi-class companies (GOOGL and GOOG) have one company and several tickers |
| `facts` | Company, metric, period | `cik`, `metric`, `period_start` (null for balance sheet items), `period_end`, `fiscal_period` (FY, or Q1 to Q3 for year-to-date periods), `value`, `form`, `filed_at`, `accession`, `source_tag` (`derived` when computed from other metrics) |
| `ratios` | Company | `cik`, `as_of`, `ttm_basis`, `fundamentals_through`, one column per ratio on the stock page, the inputs that price-based ratios need (`shares_outstanding`, `equity`, `debt`, `cash`, `eps_ttm`, ...), `lynch_category`, `lynch_score` |
| `ratio_history` | Company, fiscal year | `cik`, `fiscal_year`, the same ratio columns, used for the 5-year range bars |
| `sector_medians` | Sector | `sector`, `as_of`, median of each ratio |
| `prices_daily` | Ticker, day | `ticker`, `date`, `open`, `high`, `low`, `close` |
| `quotes` | Ticker | `ticker`, `price`, `change`, `change_pct`, `prev_close`, `open`, `high`, `low`, `quote_time`, `fetched_at` |
| `price_fetches` | Ticker | `ticker`, `fetched_at`, `first_date`, `last_date`: when bars were last topped up, so a cold stock is not re-requested on every open |
| `filings` | Company, filing | `cik`, `accession`, `form`, `period`, `filed_at`, `title`, `url`. Keyed by both: one filing can be listed under several companies |
| `watchlist` | Ticker | `ticker`, `added_at`, `position` |
| `company_views` | Stock page open | `cik`, `viewed_at`. Kept for 30 days, for the promotion rule |
| `job_runs` | Background job | `name`, `started_at`, `finished_at`, `ok`, `detail`, `cursor` |
| `insider_trades` | Form 4 transaction | `cik`, `filed_at`, `person`, `role`, `code`, `shares`, `price` |
| `transactions` | Trade or cash movement | `id`, `date`, `type`, `ticker`, `shares`, `price`, `amount`, `note` |
| `portfolio_daily` | Day | `date`, `value`, `cash`, `net_deposits`, `return_index` |

- `facts.metric` is the app's own name, such as `revenue` or `net_income`. `source_tag` records which XBRL tag supplied it, for debugging.
- `companies.tier` is `warm` or `cold`. See the next section.
- Price tables are keyed by ticker, not CIK, so index funds and ETFs that have no row in `companies` can still be priced and held in the portfolio.
- Sector comes from the SIC code in the EDGAR submissions data, mapped to about 25 readable groups in `pipeline/sector.py`.

## Tiering and refresh

Fundamentals are local for every company. Only prices are tiered, because quotes are the one scarce thing on free plans.

| | Warm tier | Cold tier |
| --- | --- | --- |
| Who | S&P 500, the watchlist, portfolio holdings, anything opened 3 times in 30 days | Every other US filer |
| Fundamentals and ratios | In the database | In the database |
| Quote | Refreshed in a loop during market hours | Fetched when the stock is opened, then cached |
| Price history | Updated nightly | Fetched on first open, topped up on later opens |
| Time to open | Instant | About a second on first open, instant after |

The S&P 500 list is used instead of the Fortune 500, because Fortune ranks by revenue and includes private companies with no ticker. Keep the list in `backend/app/data/sp500.csv` and refresh it by hand a few times a year.

**Jobs**

1. **Bulk load, once (`make bulk`).** Download `companyfacts.zip` (1.4 GB) and `submissions.zip` (1.6 GB), skipping a download when the local copy is as new as EDGAR's. Read them one company at a time straight out of the zip, never unzipping to disk, and fill `companies`, `tickers`, `facts`, `filings`, and `ratios`. The universe is every CIK in EDGAR's ticker list (about 8,000 companies). The zips are deleted afterwards unless `--keep` is passed, since EDGAR rebuilds them nightly. `ratio_history` and `sector_medians` come in phase 5. All-caps EDGAR names are tidied ("ACME UNITED CORP" becomes "Acme United Corp").
2. **New filings, twice a day (6:30 a.m. and 10:30 p.m. New York time, and a minute after startup).** Read EDGAR's `master.YYYYMMDD.idx` for each day since the last run. A 10-K or 10-Q reloads the company's facts and ratios; an 8-K or Form 4 refreshes its filings list only. EDGAR's companyfacts can lag a filing by days, so a company whose facts do not yet include the new report is retried on later runs for a week. New listings that are not yet in `companies` are picked up by the next bulk load. Sector medians are recomputed at the end from phase 5.
3. **Quote loop, market hours.** Cycle through the warm tier at the configured rate. At 50 calls per minute, about 520 names take roughly 10 minutes per pass. Pause outside 9:30 a.m. to 4:00 p.m. ET and on weekends.
4. **Daily bars, nightly.** One Alpaca multi-symbol request per batch of warm tickers for the latest daily bar.
5. **Promotion, nightly (2:00 a.m.).** Set `tier = warm` for any cold company opened 3 or more times in the last 30 days, counted from `company_views`. Demote anything unopened for 90 days that is not in the S&P 500, the watchlist, or the portfolio.

Each job's last run, result, and position are kept in `job_runs` and shown by `/api/status`.

**On-request path for a cold stock**

1. Ratios and filings are read from the database and returned at once.
2. In parallel, the fetcher gets a Finnhub quote and Alpaca daily bars since 2016.
3. The page renders fundamentals first, then fills in the price and chart when they arrive. Price-based ratios such as P/E are recomputed with the fresh price.
4. Everything fetched is stored, so the next open is instant.

A quote older than 15 minutes during market hours, or from before the latest close when the market is shut, is shown with its age and refreshed in the background. A missing quote is handled the same way: the page never waits on Finnhub. It renders with what is stored and polls every 1.5 seconds until the fresh quote lands.

## Fundamentals pipeline

EDGAR gives raw reported numbers, so the app computes every ratio itself in three steps: map tags to metrics, build trailing-twelve-month figures, then apply formulas. This layer is where most of the effort goes, and it is the part most worth testing.

**Step 1: map XBRL tags to metrics**

Companies tag the same line item differently. For each metric, try the tags in order and take the first that has data for the period. All tags are in the `us-gaap` taxonomy unless marked.

| Metric | Tags, in priority order |
| --- | --- |
| `revenue` | `RevenuesNetOfInterestExpense` when present (banks, brokers). Otherwise the **largest** of `RevenueFromContractWithCustomerExcludingAssessedTax`, `Revenues`, `SalesRevenueNet`, `RevenueFromContractWithCustomerIncludingAssessedTax`, contract revenue + `OperatingLeaseLeaseIncome` (REITs, lessors), and `InterestIncomeExpenseNet` + `NoninterestIncome` (banks). See the note below the table |
| `cost_of_revenue` | `CostOfRevenue`, `CostOfGoodsAndServicesSold`, `CostOfGoodsSold`, `CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization` |
| `gross_profit` | `GrossProfit`, else `revenue` minus `cost_of_revenue` |
| `operating_income` | `OperatingIncomeLoss` |
| `pretax_income` | `IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest`, `IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments` |
| `income_tax` | `IncomeTaxExpenseBenefit` |
| `net_income` | `NetIncomeLoss`, `NetIncomeLossAvailableToCommonStockholdersBasic`, `ProfitLoss` |
| `eps_diluted` | `EarningsPerShareDiluted`, `IncomeLossFromContinuingOperationsPerDilutedShare`, `EarningsPerShareBasic`, else `net_income` / `shares_diluted` for the same period (multi-class companies report EPS only per class) |
| `shares_diluted` | `WeightedAverageNumberOfDilutedSharesOutstanding` |
| `shares_outstanding` | `dei:EntityCommonStockSharesOutstanding`, `CommonStockSharesOutstanding` |
| `depreciation_amortization` | `DepreciationDepletionAndAmortization`, `DepreciationAndAmortization`, `DepreciationAmortizationAndAccretionNet`, else `Depreciation` + `AmortizationOfIntangibleAssets` |
| `interest_expense` | `InterestExpense`, `InterestExpenseNonoperating`, `InterestExpenseDebt` |
| `cash` | `CashAndCashEquivalentsAtCarryingValue`, `CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents`, `Cash`, `CashAndDueFromBanks`, plus `ShortTermInvestments` when present |
| `debt` | Noncurrent (`LongTermDebtNoncurrent`, `LongTermDebtAndCapitalLeaseObligations`, `UnsecuredLongTermDebt`, `SeniorLongTermNotes`, `LongTermNotesPayable`, `LongTermNotesAndLoans`, `ConvertibleLongTermNotesPayable`, `ConvertibleDebtNoncurrent`) + current (`DebtCurrent` if reported, else `LongTermDebtCurrent` or `LongTermDebtAndCapitalLeaseObligationsCurrent` or `ConvertibleNotesPayableCurrent` or `NotesPayableCurrent`, plus `ShortTermBorrowings` + `CommercialPaper`). Else `LongTermDebt` or `LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities`, plus `ShortTermBorrowings` + `CommercialPaper`. Else `DebtLongtermAndShorttermCombinedAmount`, `DebtAndCapitalLeaseObligations`, `NotesPayable`, `SeniorNotes`. Else short-term debt alone |
| `equity` | `StockholdersEquity`, `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest` |
| `total_assets` | `Assets` |
| `current_assets` | `AssetsCurrent` |
| `current_liabilities` | `LiabilitiesCurrent` |
| `inventory` | `InventoryNet` |
| `operating_cash_flow` | `NetCashProvidedByUsedInOperatingActivities`, `NetCashProvidedByUsedInOperatingActivitiesContinuingOperations` |
| `capex` | `PaymentsToAcquirePropertyPlantAndEquipment`, `PaymentsToAcquireProductiveAssets`, `PaymentsForCapitalImprovements`, `PaymentsToAcquireOilAndGasPropertyAndEquipment` |
| `dividends_per_share` | `CommonStockDividendsPerShareDeclared`, `CommonStockDividendsPerShareCashPaid` |

The map started from general knowledge of the taxonomy and was extended in phase 1 from the coverage report (`make coverage`), which shows per metric how many S&P 500 companies resolve. Extend it the same way: run the report, look at which tags the missing companies use, add them, re-run.

**Why revenue is "largest", not "first".** The spec's original order put `RevenueFromContractWithCustomerExcludingAssessedTax` first. That tag covers ASC 606 contract revenue only. It leaves out rent (ASC 842), interest, and insurance premiums, so for REITs, lessors, banks, and insurers it is a small slice of revenue: Essex Property Trust showed $10M of revenue against $410M of net income. Taking the largest candidate per period gives the top line whichever tags a company uses. Lease income on its own is never revenue, since for most companies it is a side item.

**Gaps the free API cannot fill.** The companyfacts API only returns facts that apply to the whole company, without dimensions. Companies that report a line only by segment or class have no value for it. Known cases: Caterpillar, Ford, and GM split debt between industrial and finance arms; APA reports revenue only by product; Visa, Berkshire, Hershey, and other multi-class companies report EPS only per class (EPS falls back to net income over diluted shares where that exists). These stay blank rather than estimated.

**EDGAR can lag a filing.** Visa's 10-Q filed 2026-07-29 was not in its companyfacts on 2026-10-07, so Visa's figures ran through March. The nightly refresh (phase 4) picks such filings up once EDGAR does.

**Predecessor companies.** When a new holding company replaces a filer, its history stays under the old CIK. `backend/app/data/predecessors.csv` maps the new CIK to the old one and the loader merges their facts, the newer filing winning where both report a period. ExxonMobil Holdings (2026) is the first entry.

The 90% coverage target in phase 1 applies to the core metrics, which every operating company reports: `revenue`, `net_income`, `eps_diluted`, `equity`, `total_assets`, `shares_outstanding`, `operating_cash_flow`, `cash`, and `debt`. The other metrics do not exist for every business (banks have no inventory or gross profit, many companies pay no dividend), so the report shows their coverage among the companies they apply to but does not gate the phase. Banks need extra revenue tags to reach 90% on `revenue`.

**Step 2: build clean periods**

- Use each fact's own `start` and `end` dates to decide what period it covers. Do not trust the `fy` and `fp` fields for this. They describe the filing the fact appeared in, so prior-year comparison numbers carry the wrong year.
- The same period appears in several filings. Keep the value with the latest `filed` date, which picks up restatements.
- Income and cash flow facts in a 10-Q come as 3-month and year-to-date figures. There is no separate fourth quarter.
- Balance sheet facts are point-in-time. Read every balance sheet item on the latest balance sheet date. An item last reported on an older date (debt since paid off, say) is missing, not stale.
- A year-to-date period starts the day after a fiscal year end and runs 75 to 300 days. The window is wide because some retailers (Kroger, AutoZone) use 16-week quarters. The prior-year figure is the period of the same length (within 10 days) ending about a year earlier.
- Fiscal years are named by the calendar year they end in. A 52/53-week year ending in the first week of January belongs to the year before.
- Growth rates (1, 3, 5 years) compare fiscal-year values, not trailing twelve months.

Trailing twelve months for any income or cash flow metric:

```
TTM = FY_last + YTD_current - YTD_prior_year
```

If the latest filing is a 10-K, TTM is simply the fiscal year.

**Step 3: formulas**

| Ratio | Formula |
| --- | --- |
| Market cap | price × `shares_outstanding` |
| P/E, trailing | price / TTM `eps_diluted` |
| EPS growth, N years | compound annual growth of fiscal-year `eps_diluted` over N years. Blank if either end is zero or negative |
| PEG | P/E / 5-year EPS growth in percent. Fall back to 3-year if 5 is unavailable |
| Price to sales | market cap / TTM `revenue` |
| Price to book | market cap / `equity` |
| Enterprise value | market cap + `debt` - `cash` |
| EBITDA | TTM `operating_income` + TTM `depreciation_amortization` |
| EV / EBITDA | enterprise value / EBITDA |
| Free cash flow | TTM `operating_cash_flow` - TTM `capex` |
| Free cash flow yield | free cash flow / market cap |
| Gross, operating, net margin | TTM `gross_profit`, `operating_income`, `net_income`, each / TTM `revenue` |
| Return on equity | TTM `net_income` / average of `equity` now and one year ago |
| Return on invested capital | TTM `operating_income` × (1 - tax rate) / (`equity` + `debt` - `cash`). Tax rate is TTM `income_tax` / TTM `pretax_income`, clamped to 0 to 35% |
| Cash conversion | free cash flow / TTM `net_income` |
| Debt to equity | `debt` / `equity` |
| Net cash per share | (`cash` - `debt`) / `shares_outstanding` |
| Net debt / EBITDA | (`debt` - `cash`) / EBITDA |
| Current ratio | `current_assets` / `current_liabilities` |
| Interest coverage | TTM `operating_income` / TTM `interest_expense` |
| Inventory turnover | TTM `cost_of_revenue` / average `inventory` |
| Dividend yield | TTM `dividends_per_share` / price |

Ratios that use price are recomputed whenever a new quote arrives. The rest change only when a filing does.

**Known traps**

- **Missing is blank, never zero.** A ratio with a missing input is stored as null and shown as a dash.
- **Banks and insurers** have no gross profit, EBITDA, or current ratio. Leave those blank for SIC codes 6000 to 6499.
- **Multi-class shares.** The EDGAR APIs only return facts that apply to the whole company, so share counts split by class can be missing. Fall back to the latest `shares_diluted`.
- **Foreign filers** on forms 20-F and 40-F often use the `ifrs-full` taxonomy. Version 1 covers `us-gaap` filers only and labels the others as unsupported.
- **Stock splits** change EPS and share counts across history. EPS history from the latest 10-K is already restated for the years it covers. Older years are restated by comparing each filing's values with the newer filing's values for the same periods: a ratio that matches a split (2, 3, 4, 10, 20, and so on, or a reverse split) rescales everything only that older filing covers. NVIDIA's fiscal 2021 EPS of $6.90 becomes $0.17 after its 4-for-1 and 10-for-1 splits. A split inside the current fiscal year, before the next 10-K, is not caught: trailing EPS can mix bases for those months.
- **Fiscal years** do not all end in December. Sector medians compare each company's latest TTM, whatever month it ends.

**Sector medians and 5-year range**

- Sector median: the median of each ratio across companies in the same sector group with a market cap above $300M. Recomputed nightly.
- 5-year range: the low and high of the ratio across the last five fiscal year ends in `ratio_history`. Price-based ratios in history use the closing price on each fiscal year end date.

**Tests**

Save the `companyfacts` JSON for 10 well-known companies as fixtures. For each, assert revenue, net income, diluted EPS, and equity for the last fiscal year against the figures printed in the 10-K, within 1%. These tests are the acceptance gate for the whole pipeline. Each fixture is trimmed to the tags in the map above, so it stays EDGAR JSON but small enough for the repo. Each test cites the 10-K it checks against.

## Lynch check

Every stock gets one of Lynch's six categories and a score out of 100 built from nine tests. The thresholds below are starting values. Keep them all in `pipeline/lynch_config.py` so they can be tuned without touching logic.

**Category, first match wins**

| Category | Rule |
| --- | --- |
| Turnaround | Net loss in either of the last two fiscal years, and TTM net income is positive or the loss is shrinking |
| Asset play | Price to book under 1.0, or net cash per share above 30% of the price |
| Cyclical | Sector is on the cyclical list (autos, airlines, steel, chemicals, homebuilders, energy, semiconductors), or EPS fell more than 30% in two or more of the last ten years |
| Fast grower | 5-year EPS growth of 20% or more and 5-year revenue growth of 15% or more |
| Stalwart | 5-year EPS growth of 10% to 20% |
| Slow grower | Everything else with positive earnings |

**The nine tests**

| Test | Passes when | Watch when | Weight |
| --- | --- | --- | --- |
| PEG | Under 1.0 | 1.0 to 1.5 | 20 |
| EPS growth | 5-year above 15% | 10% to 15% | 15 |
| P/E range | Between 5 and 25 | 25 to 35 | 10 |
| Revenue growth holding up | 1-year growth is at least 90% of the 5-year rate | 60% to 90% | 10 |
| Debt to equity | Under 0.5 | 0.5 to 1.0 | 10 |
| Inventory vs sales | Inventory grew slower than revenue over the last year | Within 5 points faster | 10 |
| Insider buying | More open-market buys than sells in the last 6 months | No activity | 10 |
| Market cap | $300M to $10B | $10B to $50B | 10 |
| Net cash | Cash exceeds debt | Net debt under 1× EBITDA | 5 |

A pass earns the full weight, a watch earns half, a fail earns nothing. A test with missing data is left out and the remaining weights are rescaled to 100. The page shows each test's value and status, so the score is never a black box.

Insider activity comes from Form 4 filings. Transaction code `P` is an open-market purchase and `S` is a sale. Ignore option exercises and grants.

Banks skip the inventory test. Companies with no inventory skip it too.

## Interface

The app has four screens: stock page, search, portfolio, and screener. The stock page is the one to get right first. The files in `design/` are the visual reference. They use made-up companies, so copy their layout and style, not their numbers. The stock page mockup's "Watchlists" tab is dropped: the watchlist lives in the left column of the stock page.

**Look**

The look takes cues from professional trading terminals without copying one: true black, an amber accent, square corners, dense rows, and every panel topped by a title bar with an uppercase monospace label. Each panel has a number, and pressing that number key jumps to it. The search box is a command line with a prompt. Selected items use inverse colors, amber fill with black text. No blue anywhere. Gains and losses always carry a plus or minus sign as well as a color. The layout must work at phone width: the watchlist stacks above the content and the cards go single column.

| Token | Value |
| --- | --- |
| Page background | `#000000` |
| Panel background | `#0A0A0A` |
| Panel title bar | `#141414` |
| Borders | `#2A2A2A` |
| Row dividers | `#1A1A1A` |
| Text | `#F2F2F2` |
| Secondary text | `#C8C8C8` |
| Muted text | `#9A9A9A` |
| Accent | `#FFA31A` |
| Up | `#2BD67B` |
| Down | `#FF4D4D` |
| Watch | `#FFE14D` |
| Interface font | IBM Plex Mono, used for everything except company names and row labels |
| Label font | IBM Plex Sans, for company names and row labels |

**Stock page, top to bottom**

1. **Header.** Ticker, name, exchange, sector, Lynch category, price, day change, and a strip with market cap, P/E, PEG, Lynch score, and the 52-week range.
2. **Price chart.** Full width and the tallest element on the page, about 500 px. Candlesticks by default with a switch to a line, and range buttons for 1M, 6M, YTD, 1Y, 5Y, and Max. Daily candles up to 6M, weekly beyond. An open, high, low, close readout above the chart and a marker for the last price on the axis. No volume, since the free feed covers one exchange. The chart is the owner's favorite part of the page, so give it the most care.
3. **Lynch check.** Full width under the chart. Score and category chips on the left, the nine tests in two columns on the right at a larger type size, each with its value and a Pass or Watch pill.
4. **Four ratio cards.** Valuation, Growth, Quality, Balance sheet. Each row shows the value now, a bar placing it inside the stock's own 5-year range, and the sector median. Growth shows 1, 3, and 5 year rates instead of a range bar. Growth rates are gains and losses, so they carry a sign and a color.
5. **10-year trend.** Bars for fiscal-year revenue and EPS.
6. **Recent filings.** The latest 10-K, 10-Q, 8-K, and Form 4 entries, each linking to the filing on sec.gov.
7. **Source line.** Where each number came from and how old it is.

The watchlist sits in a left column on the stock page, with warm names and their quotes, then recently viewed cold names.

**Search**

- Opens with the `/` key from anywhere. Up and Down move, Enter opens, Esc closes, Tab adds to the watchlist. (`W` cannot do this inside the search box, since it is also a letter people type: WMT, WFC. On the stock page `W` toggles the watchlist.)
- Matches ticker prefix first, then company name. Runs against the local `companies` table, so results appear as the user types.
- Results are grouped: warm names with their price, then everything else with a note on whether it is cached.

**Screener**

Filters on any stored ratio, sector, market cap, and Lynch category, with sortable columns. Ships with one saved preset, "Lynch fast growers": PEG under 1.0, EPS growth above 15%, debt to equity under 0.5, market cap $300M to $10B.

**Speed rules**

- Stock page data comes from one endpoint and one database read. Target under 100 ms on the backend for a warm stock.
- Hovering a watchlist row or search result prefetches that stock, so the click feels instant.
- Fundamentals render first. Price and chart fill in when ready, with fixed-size placeholders so nothing shifts.
- Keep the previous stock on screen until the next one is ready. No full-page spinners.

**API**

| Endpoint | Returns |
| --- | --- |
| `GET /api/stock/{ticker}` | Everything the stock page needs, with a `fetched_at` per source |
| `GET /api/stock/{ticker}/prices?range=1y` | Daily open, high, low, and close for the chart |
| `GET /api/search?q=` | Up to 8 matches, grouped by tier |
| `GET /api/screener` | Rows matching the filter query |
| `GET, POST, DELETE /api/watchlist` | Watchlist with quotes |
| `GET /api/portfolio` | Summary, holdings, allocation, and look-through in one call |
| `GET /api/portfolio/performance?range=1y` | Daily portfolio and benchmark return series |
| `GET, POST, PUT, DELETE /api/transactions` | The trade log |
| `GET /api/status` | Job health, last run times, counts per tier |

## Portfolio

The portfolio page tracks real holdings, built from a log of trades, and sits beside the stock page as a top-level tab. `design/portfolio.dc.html` has the layout.

**How it works**

- The portfolio is a log of transactions entered by hand: buy, sell, deposit, withdrawal, dividend. Shares, average cost, and cash are always derived from that log, never typed in directly.
- Cost basis uses the average cost method. A sell reduces shares at average cost and records the realized gain.
- A buy that costs more than the cash on hand counts the shortfall as money brought in (an implicit deposit), so someone who logs only trades still gets correct returns. Selling more shares than are held, or withdrawing more than the cash, is refused with the reason, and so is any edit or delete that would make a later entry impossible.
- Same-day entries apply in this order: deposits, dividends, sells, buys, withdrawals, so a deposit funds a buy on the same day.
- A ticker in a trade must be a known company or have a Finnhub quote (index funds and ETFs). Funds show "Fund" as their category and are not linked to a stock page.
- Every holding joins the warm tier automatically, so its quote stays fresh. Funds have no company row, so the quote loop and nightly bars include every held ticker directly.
- Clicking a holding opens its stock page.

**Page, top to bottom**

1. **Header.** Total value, day change, total gain in dollars and percent, cost basis, cash, 1-year return against the benchmark, and an Add trade button on the `T` key.
2. **Performance.** Portfolio return against the S&P 500, drawn as two lines, with ranges 1M, 6M, YTD, 1Y, and All.
3. **Allocation.** Horizontal bars by Lynch category and by sector.
4. **Holdings.** One row per position: shares, average cost, price, day change, value, gain, gain percent, weight, Lynch category, Lynch score, P/E, PEG. Sortable by any column, with a cash row and a total row.
5. **Look-through.** The stocks treated as one company: P/E, EPS growth, PEG, Lynch score, largest stock weight, and how many positions sit below cost.
6. **Activity.** The latest trades and cash movements.
7. **Filings from your holdings.** The newest 10-K, 10-Q, 8-K, and Form 4 filings across everything held.

**Calculations**

- Position value is shares times the latest quote. Daily history uses closes from `prices_daily`.
- `portfolio_daily` is rebuilt from the first trade date whenever a trade is added, edited, or deleted, and after the nightly bars job. Trading days come from SPY's bars. A holding with no close yet is valued at its trade price.
- Returns are time-weighted, so a deposit never counts as a gain. With `V` as the day's closing value and `F` as net deposits that day, the daily return is:

```
r_t = (V_t - F_t) / V_(t-1) - 1
```

- The benchmark is SPY daily closes from Alpaca over the same dates. Both lines start at 0% at the beginning of the chosen range. "1Y vs benchmark" in the header is the difference in percentage points over the last year, or since the first trade if that is shorter.
- "Total gain" in the header is unrealized: holdings value minus cost basis. Realized gains and dividends are in the API but not on the page yet.
- Look-through P/E is total stock value divided by the holdings' share of earnings, not an average of P/Es. EPS growth and Lynch score are weighted by value. PEG is that P/E over that growth.

**Limits on free data**

- **Dividends.** The free price feeds do not include them, so returns are price-only unless a dividend is logged as a transaction.
- **Index funds and ETFs.** Price, value, and gains work. EDGAR has no company fundamentals for them, so the Lynch columns show a dash and they are left out of look-through.
- **History.** Alpaca's free bars start in January 2016, so the performance chart cannot go back further.

Trades live only in the local database, which is gitignored. Demo mode ships with made-up holdings so the page works on a fresh clone.

## GitHub

The code lives in a public repo at `github.com/ericpeck05/tenbagger`, set up so a stranger can read it, run it, and never see a key.

**Keeping secrets out**

- All keys load from a `.env` file that is gitignored from the first commit. The repo carries `.env.example` with empty values for `FINNHUB_API_KEY`, `ALPACA_KEY_ID`, `ALPACA_SECRET_KEY`, and `SEC_USER_AGENT`.
- `SEC_USER_AGENT` holds the contact email EDGAR requires. It stays in `.env`, not in code.
- `.gitignore` covers `.env`, `data/`, `*.db`, `*.zip`, `node_modules/`, and build output.
- Turn on GitHub secret scanning and push protection for the repo, and add a `gitleaks` pre-commit hook.
- Nothing fetched from Finnhub or Alpaca is ever committed. Test fixtures use EDGAR JSON only, which is free to reuse.

**Making it worth visiting**

- **README:** one-paragraph pitch, a screenshot of the stock page, a short screen recording of search, a three-step quick start, the architecture diagram, the data sources with their limits, and a note that this is a research tool and not investment advice.
- **Demo mode:** `make demo` runs the app on bundled sample data with no keys, so anyone who clones it sees a working page in a minute.
- **License:** MIT.
- **CI:** a GitHub Actions workflow runs `ruff`, `pytest`, and the frontend type check on every push.
- **History:** one pull request per build phase, each with a short description of what it adds, and a version tag when the phase is done.

## Build phases

Eight phases, each ending in something that runs. Finish and merge one before starting the next.

| Phase | Builds | Done when |
| --- | --- | --- |
| 0. Scaffold | Repo, backend and frontend skeletons, `.env.example`, `.gitignore`, CI, `make dev` | A placeholder page loads at localhost, CI is green, and the public repo is live with no secrets in it |
| 1. Fundamentals | EDGAR adapter, tag map, TTM builder, ratio formulas, loaded for the S&P 500 through the per-company API | The 10 fixture companies pass within 1%, and the coverage script shows each core metric resolving for at least 90% of the S&P 500 |
| 2. Stock page | Finnhub and Alpaca adapters, quote loop, stock page, search, watchlist | Any S&P 500 stock opens in under a second and the page matches the mockup |
| 3. Portfolio | Transaction log, add-trade form, holdings table, allocation, performance against the benchmark | Entering a handful of trades produces the right shares, average cost, value, and gain, checked by hand, and the chart draws both lines |
| 4. Whole market | Bulk load, warm and cold tiers, on-request path, nightly jobs, promotion | A small-cap that was never opened loads in about a second, then instantly the second time |
| 5. Lynch check | Categories, nine tests, score, Form 4 insider trades, sector medians, 5-year ranges, and the Lynch columns and look-through on the portfolio page | Every ratio row shows its range bar and sector median, and each score can be traced to its nine inputs |
| 6. Screener | Filter and sort across all companies, the saved Lynch preset | A screen across the full market returns in under a second |
| 7. Polish | Phone layout, hover prefetch, demo mode, README with screenshots, `v1.0` tag | A fresh clone runs with `make demo` and no keys |

Phase 1 deliberately uses the per-company API for about 500 names, which takes a couple of minutes at 8 requests per second. That proves the pipeline on familiar companies before the large bulk file comes in at phase 4.

Until phase 5 lands, the stock page shows the Lynch panel, range bars, and sector medians as empty placeholders, and the portfolio page shows dashes in its Lynch columns.

## Later and open questions

**Parked**

- **Social.** Still undecided between pulling in outside chatter, sharing with a small group, or a public platform. One constraint is already known: only numbers derived from EDGAR can be shown to other people. Finnhub and Alpaca free data is for personal use.
- **Hosted version.** A free path exists. A nightly GitHub Action could compute the EDGAR ratios and publish them as static files to GitHub Pages, giving visitors fundamentals without prices.
- **Filing summaries.** A plain-English summary of the latest 10-K or 10-Q per stock. A local model keeps it free. An API model costs a little per summary.
- **Forward estimates.** Forward P/E and analyst targets need a paid source. The data adapters are built so one can be added later.

**Open**

- [x] Confirm Finnhub's free rate limit with a real key, and set the quote loop to match. (60 per minute; the loop uses 45 of the configured 50.)
- [ ] Decide the final name. "Tenbagger" is a placeholder.
- [ ] Decide whether the portfolio should also hold crypto, and whether to add CSV import from a brokerage export.
