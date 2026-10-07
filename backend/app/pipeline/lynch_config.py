"""Every threshold the Lynch check uses, in one place so they can be tuned without touching
the logic in lynch.py. Growth rates and margins are fractions (0.15 is 15%)."""

# ---- Category rules, first match wins (SPEC.md, "Lynch check")
TURNAROUND_LOOKBACK_YEARS = 2  # a net loss in either of the last two fiscal years
ASSET_PLAY_MAX_PB = 1.0  # price to book under 1.0 ...
ASSET_PLAY_NET_CASH_SHARE = 0.30  # ... or net cash per share above 30% of the price
CYCLICAL_EPS_DROP = 0.30  # EPS fell more than 30% in a year ...
CYCLICAL_DROP_YEARS = 2  # ... in two or more of the last ten years
FAST_GROWER_EPS_5Y = 0.20
FAST_GROWER_REVENUE_5Y = 0.15
STALWART_EPS_5Y = (0.10, 0.20)

# ---- The nine tests: (pass, watch) bands and weights. Weights sum to 100.
PEG_PASS_BELOW = 1.0
PEG_WATCH_BELOW = 1.5
EPS_GROWTH_PASS_ABOVE = 0.15
EPS_GROWTH_WATCH_ABOVE = 0.10
PE_PASS = (5.0, 25.0)
PE_WATCH = (25.0, 35.0)
REVENUE_HOLDING_PASS = 0.90  # 1-year growth at least 90% of the 5-year rate
REVENUE_HOLDING_WATCH = 0.60
DEBT_EQUITY_PASS_BELOW = 0.5
DEBT_EQUITY_WATCH_BELOW = 1.0
INVENTORY_WATCH_POINTS = 0.05  # inventory growing up to 5 points faster than sales
INSIDER_WINDOW_DAYS = 182
MARKET_CAP_PASS = (300e6, 10e9)
MARKET_CAP_WATCH = (10e9, 50e9)
NET_DEBT_EBITDA_WATCH_BELOW = 1.0

WEIGHTS = {
    "peg": 20,
    "eps_growth": 15,
    "pe": 10,
    "revenue_holding": 10,
    "debt_to_equity": 10,
    "inventory": 10,
    "insiders": 10,
    "market_cap": 10,
    "net_cash": 5,
}

# ---- Sector medians
MEDIAN_MIN_MARKET_CAP = 300e6
RANGE_YEARS = 5
