"""Report, per metric, how many S&P 500 companies resolve a current value.

    python -m app.jobs.coverage            # summary table
    python -m app.jobs.coverage --missing  # also list the companies missing each metric

Reads the EDGAR downloads cached by `load_sp500`, so it runs offline in seconds. A metric
"resolves" when the company has a value for its latest period: a trailing-twelve-month
figure that is not older than the company's newest data, or a balance sheet value on the
latest balance sheet date.
"""

import argparse
import sys
from datetime import timedelta

from app.jobs.load_sp500 import _cache_path, read_predecessors, read_sp500
from app.pipeline import ttm as T
from app.pipeline.ratios import BALANCE_METRICS, TTM_METRICS
from app.pipeline.sector import is_financial
from app.pipeline.tags import extract, is_foreign_filer, merge_companyfacts

CORE = (
    "revenue",
    "net_income",
    "eps_diluted",
    "equity",
    "total_assets",
    "shares_outstanding",
    "operating_cash_flow",
    "cash",
    "debt",
)
NOT_FOR_FINANCIALS = {
    "cost_of_revenue",
    "gross_profit",
    "current_assets",
    "current_liabilities",
    "inventory",
}
REPORTED = (
    *CORE,
    "cost_of_revenue",
    "gross_profit",
    "operating_income",
    "pretax_income",
    "income_tax",
    "depreciation_amortization",
    "interest_expense",
    "capex",
    "dividends_per_share",
    "current_assets",
    "current_liabilities",
    "inventory",
    "shares_diluted",
)
STALE_AFTER = timedelta(days=100)


def resolved_metrics(facts: dict) -> set[str]:
    """Metrics with a current value for this company."""
    sheet = T.latest(facts.get("total_assets", {})) or T.latest(facts.get("equity", {}))
    flows = {m: T.ttm(facts.get(m, {})) for m in (*TTM_METRICS, "eps_diluted")}
    newest = max(
        [t.end for t in flows.values() if t] + ([sheet.end] if sheet else []), default=None
    )
    out = set()
    for m, t in flows.items():
        if t is not None and newest is not None and newest - t.end <= STALE_AFTER:
            out.add(m)
    if sheet is not None:
        out |= {m for m in BALANCE_METRICS if T.at(facts.get(m, {}), sheet.end)}
    if T.latest(facts.get("shares_outstanding", {})) or facts.get("shares_diluted"):
        out.add("shares_outstanding")
    if any(T.is_annual(f) for f in facts.get("shares_diluted", {}).values()):
        out.add("shares_diluted")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--missing", action="store_true")
    args = parser.parse_args(argv)

    import gzip
    import json

    universe = read_sp500()
    predecessors = read_predecessors()
    results: dict[str, set[str]] = {}
    financial: set[str] = set()
    skipped: list[str] = []
    for cik, entry in universe.items():
        label = entry["tickers"][0]
        cf_path, sub_path = _cache_path("companyfacts", cik), _cache_path("submissions", cik)
        if not cf_path.exists() or not sub_path.exists():
            skipped.append(f"{label} (not downloaded)")
            continue
        cf = json.loads(gzip.decompress(cf_path.read_bytes()))
        if cik in predecessors and _cache_path("companyfacts", predecessors[cik]).exists():
            older = _cache_path("companyfacts", predecessors[cik]).read_bytes()
            cf = merge_companyfacts(cf, json.loads(gzip.decompress(older)))
        sub = json.loads(gzip.decompress(sub_path.read_bytes()))
        if is_foreign_filer(cf):
            skipped.append(f"{label} (foreign filer)")
            continue
        if is_financial(sub.get("sic")):
            financial.add(label)
        results[label] = resolved_metrics(extract(cf))

    n = len(results)
    print(f"\nCoverage across {n} S&P 500 companies ({len(financial)} banks and insurers)\n")
    print(f"{'metric':28s} {'resolved':>9s} {'of':>5s} {'pct':>7s}  core  gate")
    failing = []
    for m in REPORTED:
        pool = [t for t in results if not (m in NOT_FOR_FINANCIALS and t in financial)]
        have = [t for t in pool if m in results[t]]
        pct = 100 * len(have) / len(pool) if pool else 0.0
        core = m in CORE
        ok = pct >= 90
        if core and not ok:
            failing.append(m)
        gate = ("PASS" if ok else "FAIL") if core else ""
        print(
            f"{m:28s} {len(have):9d} {len(pool):5d} {pct:6.1f}%  "
            f"{'yes' if core else '   '}   {gate}"
        )
        if args.missing and pct < 100:
            missing = sorted(set(pool) - set(have))
            print(f"    missing: {' '.join(missing[:40])}{' ...' if len(missing) > 40 else ''}")
    if skipped:
        print(f"\nSkipped: {', '.join(skipped)}")
    print(
        "\nCore metrics at 90% or better:", "all" if not failing else f"no ({', '.join(failing)})"
    )
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main())
