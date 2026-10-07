"""Step 1 of the fundamentals pipeline: map XBRL tags to the app's own metric names.

For each metric the tags are tried in order, per period: the first tag with a value for a
period supplies it. Within one tag, the same period often appears in several filings; the
one filed last wins, which picks up restatements.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date
from statistics import median

# Forms whose facts we trust for fundamentals. 8-Ks and registration statements are skipped.
ANNUAL_FORMS = {"10-K", "10-K/A", "10-KT", "10-KT/A"}
QUARTERLY_FORMS = {"10-Q", "10-Q/A", "10-QT", "10-QT/A"}
ALLOWED_FORMS = ANNUAL_FORMS | QUARTERLY_FORMS
FOREIGN_FORMS = {"20-F", "20-F/A", "40-F", "40-F/A"}

USD = "USD"
PER_SHARE = "USD/shares"
SHARES = "shares"


@dataclass(frozen=True)
class Metric:
    name: str
    tags: tuple[str, ...]  # "us-gaap:Tag" or "dei:Tag"; bare names mean us-gaap
    unit: str = USD
    instant: bool = False  # balance sheet item (point in time) vs income or cash flow (duration)
    per_share: bool = False  # adjusted for stock splits along with share counts


METRICS: dict[str, Metric] = {
    m.name: m
    for m in [
        # Revenue is resolved differently from other metrics: see _revenue().
        Metric(
            "revenue",
            (
                "RevenueFromContractWithCustomerExcludingAssessedTax",
                "Revenues",
                "SalesRevenueNet",
                "RevenueFromContractWithCustomerIncludingAssessedTax",
            ),
        ),
        Metric("revenue_net_of_interest", ("RevenuesNetOfInterestExpense",)),
        Metric("contract_revenue", ("RevenueFromContractWithCustomerExcludingAssessedTax",)),
        Metric(
            "lease_income",
            ("OperatingLeaseLeaseIncome", "OperatingLeasesIncomeStatementLeaseRevenue"),
        ),
        Metric("net_interest_income", ("InterestIncomeExpenseNet",)),
        Metric("noninterest_income", ("NoninterestIncome",)),
        Metric(
            "cost_of_revenue",
            (
                "CostOfRevenue",
                "CostOfGoodsAndServicesSold",
                "CostOfGoodsSold",
                "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization",
            ),
        ),
        Metric("gross_profit", ("GrossProfit",)),
        Metric("operating_income", ("OperatingIncomeLoss",)),
        Metric(
            "pretax_income",
            (
                "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
            ),
        ),
        Metric("income_tax", ("IncomeTaxExpenseBenefit",)),
        Metric(
            "net_income",
            ("NetIncomeLoss", "NetIncomeLossAvailableToCommonStockholdersBasic", "ProfitLoss"),
        ),
        Metric(
            "eps_diluted",
            (
                "EarningsPerShareDiluted",
                "IncomeLossFromContinuingOperationsPerDilutedShare",
                "EarningsPerShareBasic",
            ),
            unit=PER_SHARE,
            per_share=True,
        ),
        Metric(
            "shares_diluted",
            ("WeightedAverageNumberOfDilutedSharesOutstanding",),
            unit=SHARES,
        ),
        Metric(
            "shares_outstanding",
            ("dei:EntityCommonStockSharesOutstanding", "CommonStockSharesOutstanding"),
            unit=SHARES,
            instant=True,
        ),
        Metric(
            "depreciation_amortization",
            (
                "DepreciationDepletionAndAmortization",
                "DepreciationAndAmortization",
                "DepreciationAmortizationAndAccretionNet",
            ),
        ),
        # Fallback parts for companies that report the two halves separately.
        Metric("depreciation", ("Depreciation",)),
        Metric("amortization", ("AmortizationOfIntangibleAssets",)),
        Metric(
            "interest_expense",
            ("InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt"),
        ),
        Metric(
            "cash_only",
            (
                "CashAndCashEquivalentsAtCarryingValue",
                "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
                "Cash",
                "CashAndDueFromBanks",
            ),
            instant=True,
        ),
        Metric("short_term_investments", ("ShortTermInvestments",), instant=True),
        Metric(
            "lt_debt_noncurrent",
            (
                "LongTermDebtNoncurrent",
                "LongTermDebtAndCapitalLeaseObligations",
                "UnsecuredLongTermDebt",
                "SeniorLongTermNotes",
                "LongTermNotesPayable",
                "LongTermNotesAndLoans",
                "ConvertibleLongTermNotesPayable",
                "ConvertibleDebtNoncurrent",
            ),
            instant=True,
        ),
        Metric(
            "lt_debt_current",
            (
                "LongTermDebtCurrent",
                "LongTermDebtAndCapitalLeaseObligationsCurrent",
                "ConvertibleNotesPayableCurrent",
                "NotesPayableCurrent",
            ),
            instant=True,
        ),
        Metric("debt_current_total", ("DebtCurrent",), instant=True),
        Metric("short_term_borrowings", ("ShortTermBorrowings",), instant=True),
        Metric("commercial_paper", ("CommercialPaper",), instant=True),
        Metric(
            "lt_debt_total",
            ("LongTermDebt", "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities"),
            instant=True,
        ),
        Metric(
            "debt_combined",
            (
                "DebtLongtermAndShorttermCombinedAmount",
                "DebtAndCapitalLeaseObligations",
                "NotesPayable",
                "SeniorNotes",
            ),
            instant=True,
        ),
        Metric(
            "equity",
            (
                "StockholdersEquity",
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
            ),
            instant=True,
        ),
        Metric("total_assets", ("Assets",), instant=True),
        Metric("current_assets", ("AssetsCurrent",), instant=True),
        Metric("current_liabilities", ("LiabilitiesCurrent",), instant=True),
        Metric("inventory", ("InventoryNet",), instant=True),
        Metric(
            "operating_cash_flow",
            (
                "NetCashProvidedByUsedInOperatingActivities",
                "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
            ),
        ),
        Metric(
            "capex",
            (
                "PaymentsToAcquirePropertyPlantAndEquipment",
                "PaymentsToAcquireProductiveAssets",
                "PaymentsForCapitalImprovements",
                "PaymentsToAcquireOilAndGasPropertyAndEquipment",
            ),
        ),
        Metric(
            "dividends_per_share",
            ("CommonStockDividendsPerShareDeclared", "CommonStockDividendsPerShareCashPaid"),
            unit=PER_SHARE,
            per_share=True,
        ),
    ]
}

# Metrics the rest of the app reads. Composites are built from the raw parts above.
OUTPUT_METRICS = (
    "revenue",
    "cost_of_revenue",
    "gross_profit",
    "operating_income",
    "pretax_income",
    "income_tax",
    "net_income",
    "eps_diluted",
    "shares_diluted",
    "shares_outstanding",
    "depreciation_amortization",
    "interest_expense",
    "cash",
    "debt",
    "equity",
    "total_assets",
    "current_assets",
    "current_liabilities",
    "inventory",
    "operating_cash_flow",
    "capex",
    "dividends_per_share",
)


@dataclass(frozen=True)
class Fact:
    metric: str
    start: date | None  # None for balance sheet (instant) facts
    end: date
    value: float
    form: str
    filed: date
    accession: str
    tag: str

    @property
    def period(self) -> tuple[date | None, date]:
        return (self.start, self.end)

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1 if self.start else 0


def all_tags() -> set[str]:
    """Every XBRL tag the map reads, as "taxonomy:Tag". Used to trim test fixtures."""
    return {_qualify(t) for m in METRICS.values() for t in m.tags}


def _qualify(tag: str) -> str:
    return tag if ":" in tag else f"us-gaap:{tag}"


def raw_facts(companyfacts: dict, metric: Metric, tag: str) -> list[Fact]:
    """All facts for one tag in the metric's unit, from 10-K and 10-Q filings only."""
    taxonomy, name = _qualify(tag).split(":", 1)
    entries = companyfacts.get("facts", {}).get(taxonomy, {}).get(name, {}).get("units", {})
    out = []
    for e in entries.get(metric.unit, []):
        if e.get("form") not in ALLOWED_FORMS or e.get("val") is None:
            continue
        start = date.fromisoformat(e["start"]) if "start" in e else None
        if metric.instant != (start is None):
            continue
        out.append(
            Fact(
                metric=metric.name,
                start=start,
                end=date.fromisoformat(e["end"]),
                value=float(e["val"]),
                form=e["form"],
                filed=date.fromisoformat(e["filed"]),
                accession=e["accn"],
                tag=name,
            )
        )
    return out


def latest_per_period(facts: Iterable[Fact]) -> dict[tuple, Fact]:
    """Keep the value filed last for each period."""
    best: dict[tuple, Fact] = {}
    for f in facts:
        cur = best.get(f.period)
        if cur is None or (f.filed, f.accession) > (cur.filed, cur.accession):
            best[f.period] = f
    return best


# Ratios a stock split or reverse split can produce between an old and a restated value.
_SPLIT_RATIOS = [
    2,
    3,
    4,
    5,
    6,
    7,
    8,
    10,
    12,
    15,
    20,
    25,
    30,
    35,
    40,
    50,
    60,
    70,
    75,
    80,
    100,
    120,
    150,
    200,
    250,
    300,
    400,
    500,
    1000,
    1.5,
    2.5,
    1.25,
]
_SPLIT_FACTORS = sorted({r for r in _SPLIT_RATIOS} | {1 / r for r in _SPLIT_RATIOS})


def _snap_split(ratio: float) -> float:
    """Return the split factor a restatement ratio implies, or 1.0 if it is not split-like."""
    if ratio <= 0:
        return 1.0
    for f in _SPLIT_FACTORS:
        if abs(ratio / f - 1) < 0.03:
            return f
    return 1.0


def split_adjusted(facts: Iterable[Fact]) -> dict[tuple, Fact]:
    """Latest value per period, with older filings rescaled for any stock split since.

    Each filing restates the periods it covers, so a filing made after a split shows the
    earlier periods on the new basis. Walking filings from newest to oldest, the ratio
    between a period's already-adjusted value and an older filing's raw value reveals the
    split factor for that older filing. Values only an older filing covers get that factor.
    """
    by_filing: dict[str, list[Fact]] = defaultdict(list)
    for f in facts:
        by_filing[f.accession].append(f)
    order = sorted(by_filing, key=lambda a: (by_filing[a][0].filed, a), reverse=True)

    adjusted: dict[tuple, Fact] = {}
    factor_for: dict[str, float] = {}
    for accn in order:
        rows = by_filing[accn]
        ratios = [
            adjusted[f.period].value / f.value
            for f in rows
            if f.period in adjusted and f.value != 0 and adjusted[f.period].value != 0
        ]
        factor = _snap_split(median(ratios)) if ratios else 1.0
        # An older filing with no overlap inherits the factor of the next newer filing.
        if not ratios and factor_for:
            factor = factor_for[order[order.index(accn) - 1]]
        factor_for[accn] = factor
        for f in rows:
            if f.period not in adjusted:
                adjusted[f.period] = replace(f, value=f.value * factor) if factor != 1.0 else f
    return adjusted


def resolve(companyfacts: dict, metric: Metric) -> dict[tuple, Fact]:
    """Facts for one metric, one per period, using the first tag in priority order."""
    out: dict[tuple, Fact] = {}
    for tag in metric.tags:
        facts = raw_facts(companyfacts, metric, tag)
        if metric.per_share:
            per_period = split_adjusted(facts)
        elif metric.unit == SHARES:
            # Share counts move the opposite way to per-share values in a split.
            per_period = split_adjusted(facts)
        else:
            per_period = latest_per_period(facts)
        for period, fact in per_period.items():
            out.setdefault(period, fact)
    return out


def _sum_by_end(
    base: dict[tuple, Fact], extras: list[dict[tuple, Fact]], name: str
) -> dict[tuple, Fact]:
    """Add each extra component to the base value at the same date, where present."""
    out = {}
    for period, f in base.items():
        total = f.value + sum(e[period].value for e in extras if period in e)
        out[period] = replace(f, metric=name, value=total)
    return out


def resolve_largest(companyfacts: dict, metric: Metric) -> dict[tuple, Fact]:
    """Facts for one metric, one per period, taking the largest value across its tags."""
    out: dict[tuple, Fact] = {}
    for tag in metric.tags:
        for period, fact in latest_per_period(raw_facts(companyfacts, metric, tag)).items():
            if period not in out or fact.value > out[period].value:
                out[period] = fact
    return out


def _revenue(companyfacts: dict, raw: dict[str, dict[tuple, Fact]]) -> dict[tuple, Fact]:
    """Top-line revenue per period.

    Banks and brokers that report revenue net of interest expense use that. Everyone else
    gets the largest of these candidates, which is the top line whichever tags a company
    happens to use:

    - each total-revenue tag;
    - contract revenue plus lease income: contract revenue (ASC 606) never includes rent
      (ASC 842), so for REITs and lessors the two together make the top line;
    - net interest income plus noninterest income, for banks whose contract revenue
      covers fees only.

    Lease income alone is never revenue: for most companies it is a small side item.
    """
    largest = resolve_largest(companyfacts, METRICS["revenue"])

    def offer(period: tuple, f: Fact) -> None:
        if period not in largest or f.value > largest[period].value:
            largest[period] = f

    for period, f in raw["contract_revenue"].items():
        lease = raw["lease_income"].get(period)
        if lease is not None:
            offer(period, replace(f, value=f.value + lease.value, tag="derived"))
    for period, f in raw["net_interest_income"].items():
        other = raw["noninterest_income"].get(period)
        if other is not None:
            offer(period, replace(f, value=f.value + other.value, tag="derived"))

    out = {p: replace(f, metric="revenue") for p, f in raw["revenue_net_of_interest"].items()}
    for period, f in largest.items():
        out.setdefault(period, replace(f, metric="revenue"))
    return out


def extract(companyfacts: dict) -> dict[str, dict[tuple, Fact]]:
    """Resolve every output metric for one company. Keys are (start, end) periods."""
    raw = {name: resolve(companyfacts, m) for name, m in METRICS.items()}
    out: dict[str, dict[tuple, Fact]] = {}
    for name in OUTPUT_METRICS:
        if name in raw:
            out[name] = {p: replace(f, metric=name) for p, f in raw[name].items()}
    out["revenue"] = _revenue(companyfacts, raw)

    # Gross profit: reported value, else revenue minus cost of revenue for the same period.
    gp = dict(out["gross_profit"])
    for period, rev in out["revenue"].items():
        cost = out["cost_of_revenue"].get(period)
        if period not in gp and cost is not None:
            gp[period] = replace(
                rev, metric="gross_profit", value=rev.value - cost.value, tag="derived"
            )
    out["gross_profit"] = gp

    # Cash: cash and equivalents, plus short-term investments when reported.
    out["cash"] = _sum_by_end(raw["cash_only"], [raw["short_term_investments"]], "cash")

    out["debt"] = _debt(raw)

    # EPS: companies with several share classes report EPS only per class, which the API
    # leaves out. Fall back to net income over diluted shares for the same period.
    eps = dict(out["eps_diluted"])
    for period, ni in out["net_income"].items():
        shares = out["shares_diluted"].get(period)
        if period not in eps and shares is not None and shares.value > 0:
            eps[period] = replace(
                ni, metric="eps_diluted", value=ni.value / shares.value, tag="derived"
            )
    out["eps_diluted"] = eps

    # Depreciation and amortization: the combined tag, else depreciation plus amortization.
    da = dict(out["depreciation_amortization"])
    for period, f in _sum_by_end(raw["depreciation"], [raw["amortization"]], "d").items():
        da.setdefault(period, replace(f, metric="depreciation_amortization"))
    out["depreciation_amortization"] = da
    return out


def _debt(raw: dict[str, dict[tuple, Fact]]) -> dict[tuple, Fact]:
    """Total debt per balance sheet date.

    Preferred: long-term debt excluding current maturities, plus current debt. Current debt
    is the `DebtCurrent` total when reported (it already includes short-term borrowings and
    commercial paper), else current maturities plus short-term borrowings plus commercial
    paper. Fallbacks: total long-term debt including current maturities (plus short-term
    borrowings and commercial paper, which it never includes), then a combined total.
    """
    short = [raw["short_term_borrowings"], raw["commercial_paper"]]
    debt: dict[tuple, Fact] = {}
    for period, f in raw["lt_debt_noncurrent"].items():
        if period in raw["debt_current_total"]:
            parts = [raw["debt_current_total"]]
        else:
            parts = [raw["lt_debt_current"], *short]
        debt[period] = _sum_by_end({period: f}, parts, "debt")[period]
    for period, f in _sum_by_end(raw["lt_debt_total"], short, "debt").items():
        debt.setdefault(period, f)
    for period, f in raw["debt_combined"].items():
        debt.setdefault(period, replace(f, metric="debt"))
    # Companies whose only debt is short term.
    for period, f in raw["debt_current_total"].items():
        debt.setdefault(period, replace(f, metric="debt"))
    for period, f in _sum_by_end(
        raw["short_term_borrowings"], [raw["commercial_paper"]], "debt"
    ).items():
        debt.setdefault(period, f)
    return debt


def merge_companyfacts(current: dict, predecessor: dict) -> dict:
    """Combine a company's facts with those of the entity it replaced (a new holding company,
    say). Where both report the same period, the later filing wins as usual."""
    merged = {"cik": current.get("cik"), "entityName": current.get("entityName"), "facts": {}}
    for source in (predecessor, current):
        for taxonomy, tags in source.get("facts", {}).items():
            tx = merged["facts"].setdefault(taxonomy, {})
            for tag, body in tags.items():
                units = tx.setdefault(tag, {"units": {}})["units"]
                for unit, entries in body.get("units", {}).items():
                    units.setdefault(unit, []).extend(entries)
    return merged


def is_foreign_filer(companyfacts: dict) -> bool:
    """True if the company files 20-F or 40-F and reports no us-gaap 10-K facts."""
    us = companyfacts.get("facts", {}).get("us-gaap", {})
    forms = {e.get("form") for t in us.values() for u in t.get("units", {}).values() for e in u}
    return not (forms & ANNUAL_FORMS) and bool(
        forms & FOREIGN_FORMS or "ifrs-full" in companyfacts.get("facts", {})
    )
