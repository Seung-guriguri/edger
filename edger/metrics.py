"""Turn raw XBRL company facts into tidy annual / quarterly financial tables.

The input is the DataFrame produced by ``EntityFacts.to_dataframe(include_metadata=True)``
(one row per reported fact). Companies use different tags for the same line item and
switch tags over time, so every metric has an ordered list of candidate concepts; for each
period the first concept that has a value wins.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

Period = Literal["annual", "quarterly", "ttm"]


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    kind: Literal["flow", "instant"]  # flow = duration (P&L, cash flow), instant = balance sheet
    concepts: tuple[str, ...]
    unit: Literal["money", "per_share", "shares"] = "money"


METRICS: tuple[Metric, ...] = (
    Metric("revenue", "매출", "flow", (
        "us-gaap:Revenues",
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "us-gaap:RevenueFromContractWithCustomerIncludingAssessedTax",
        "us-gaap:SalesRevenueNet",
        "us-gaap:SalesRevenueGoodsNet",
        "us-gaap:RevenuesNetOfInterestExpense",
        "ifrs-full:Revenue",
    )),
    Metric("gross_profit", "매출총이익", "flow", (
        "us-gaap:GrossProfit",
        "ifrs-full:GrossProfit",
    )),
    Metric("operating_income", "영업이익", "flow", (
        "us-gaap:OperatingIncomeLoss",
        "ifrs-full:ProfitLossFromOperatingActivities",
    )),
    Metric("net_income", "순이익", "flow", (
        "us-gaap:NetIncomeLoss",
        "us-gaap:NetIncomeLossAvailableToCommonStockholdersBasic",
        "us-gaap:ProfitLoss",
        "ifrs-full:ProfitLossAttributableToOwnersOfParent",
        "ifrs-full:ProfitLoss",
    )),
    Metric("eps", "EPS(희석)", "flow", (
        "us-gaap:EarningsPerShareDiluted",
        "us-gaap:EarningsPerShareBasicAndDiluted",
        "us-gaap:EarningsPerShareBasic",
        "ifrs-full:DilutedEarningsLossPerShare",
        "ifrs-full:BasicEarningsLossPerShare",
    ), unit="per_share"),
    Metric("ocf", "영업현금흐름", "flow", (
        "us-gaap:NetCashProvidedByUsedInOperatingActivities",
        "us-gaap:NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        "ifrs-full:CashFlowsFromUsedInOperatingActivities",
    )),
    Metric("capex", "설비투자", "flow", (
        "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment",
        "us-gaap:PaymentsToAcquireProductiveAssets",
        "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
    )),
    Metric("cash", "현금성자산", "instant", (
        "us-gaap:CashAndCashEquivalentsAtCarryingValue",
        "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "us-gaap:Cash",
        "ifrs-full:CashAndCashEquivalents",
    )),
    Metric("assets", "총자산", "instant", (
        "us-gaap:Assets",
        "ifrs-full:Assets",
    )),
    Metric("liabilities", "총부채", "instant", (
        "us-gaap:Liabilities",
        "ifrs-full:Liabilities",
    )),
    Metric("equity", "자본총계", "instant", (
        "us-gaap:StockholdersEquity",
        "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        "ifrs-full:EquityAttributableToOwnersOfParent",
        "ifrs-full:Equity",
    )),
    Metric("pretax_income", "세전이익", "flow", (
        "us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        "us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic",
        "ifrs-full:ProfitLossBeforeTax",
    )),
    Metric("income_tax", "법인세", "flow", (
        "us-gaap:IncomeTaxExpenseBenefit",
        "ifrs-full:IncomeTaxExpenseContinuingOperations",
    )),
    Metric("shares_diluted", "희석주식수", "flow", (
        "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding",
        "us-gaap:WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
        "ifrs-full:AdjustedWeightedAverageShares",
    ), unit="shares"),
    # Borrowings are tagged in many incompatible ways (see _debt_columns). These components
    # are combined there; none of them is shown on its own.
    Metric("_ltd_total", "장기차입금 합계", "instant", (
        "us-gaap:LongTermDebt",
        "us-gaap:LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities",
        "us-gaap:LongTermDebtAndFinanceLeaseObligationsIncludingCurrentMaturities",
        "ifrs-full:NoncurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings",
    )),
    Metric("_ltd_noncurrent", "장기차입금(비유동)", "instant", (
        "us-gaap:LongTermDebtNoncurrent",
        "us-gaap:LongTermDebtAndCapitalLeaseObligations",
        "us-gaap:LongTermDebtAndFinanceLeaseObligationsNoncurrent",
        "ifrs-full:NoncurrentPortionOfNoncurrentBorrowings",
        "ifrs-full:NoncurrentBorrowings",
    )),
    Metric("_ltd_current", "유동성 장기차입금", "instant", (
        "us-gaap:LongTermDebtCurrent",
        "us-gaap:LongTermDebtAndCapitalLeaseObligationsCurrent",
        "us-gaap:LongTermDebtAndFinanceLeaseObligationsCurrent",
        "ifrs-full:CurrentPortionOfNoncurrentBorrowings",
    )),
    Metric("_st_borrowings", "단기차입금", "instant", (
        "us-gaap:ShortTermBorrowings",
        "ifrs-full:ShorttermBorrowings",
    )),
    Metric("_commercial_paper", "기업어음", "instant", ("us-gaap:CommercialPaper",)),
    Metric("_other_st", "기타 단기차입금", "instant", ("us-gaap:OtherShortTermBorrowings",)),
    Metric("_debt_current", "유동 차입금 합계", "instant", (
        "us-gaap:DebtCurrent",
        "ifrs-full:CurrentBorrowings",
    )),
    Metric("_notes_payable", "사채", "instant", ("us-gaap:NotesPayable", "us-gaap:SeniorNotes")),
    Metric("_loans_payable", "대출", "instant", ("us-gaap:LoansPayable", "us-gaap:TermLoan")),
    Metric("_secured_debt", "담보부 차입", "instant", ("us-gaap:SecuredDebt",)),
    Metric("_unsecured_debt", "무담보 차입", "instant", ("us-gaap:UnsecuredDebt",)),
    Metric("_credit_line", "신용한도 차입", "instant", ("us-gaap:LineOfCredit",)),
    # IFRS filers (e.g. TSM) often report bonds separately from bank borrowings.
    Metric("_bonds_noncurrent", "사채(비유동)", "instant", ("ifrs-full:NoncurrentPortionOfNoncurrentBondsIssued",)),
    Metric("_bonds_current", "사채(유동)", "instant", (
        "ifrs-full:CurrentBondsIssuedAndCurrentPortionOfNoncurrentBondsIssued",)),
    Metric("_ifrs_lt_borrowings", "장기 차입금(IFRS)", "instant", ("ifrs-full:LongtermBorrowings",)),
    Metric("_dep", "감가상각비", "flow", ("ifrs-full:DepreciationExpense",)),
    Metric("_amort", "무형자산상각비", "flow", ("ifrs-full:AmortisationExpense",)),
    Metric("_op_lease", "운용리스부채", "instant", (
        "us-gaap:OperatingLeaseLiability",
        "ifrs-full:LeaseLiabilities",
    )),
    Metric("_fin_lease", "금융리스부채", "instant", ("us-gaap:FinanceLeaseLiability",)),
    Metric("da", "감가상각비", "flow", (
        "us-gaap:DepreciationDepletionAndAmortization",
        "us-gaap:DepreciationAmortizationAndAccretionNet",
        "us-gaap:DepreciationAndAmortization",
        "us-gaap:DepreciationAmortizationAndOther",
        "us-gaap:Depreciation",
        "ifrs-full:AdjustmentsForDepreciationAndAmortisationExpense",
        "ifrs-full:DepreciationAndAmortisationExpense",
    )),
    Metric("interest_expense", "이자비용", "flow", (
        "us-gaap:InterestExpense",
        "us-gaap:InterestExpenseNonoperating",
        "us-gaap:InterestExpenseDebt",
        "us-gaap:InterestAndDebtExpense",
        "ifrs-full:FinanceCosts",
        "ifrs-full:InterestExpense",
    )),
    Metric("dividends", "배당금 지급", "flow", (
        "us-gaap:PaymentsOfDividendsCommonStock",
        "us-gaap:PaymentsOfDividends",
        "us-gaap:PaymentsOfOrdinaryDividends",
        "ifrs-full:DividendsPaidClassifiedAsFinancingActivities",
        "ifrs-full:DividendsPaid",
    )),
    Metric("buybacks", "자사주 매입", "flow", (
        "us-gaap:PaymentsForRepurchaseOfCommonStock",
        "us-gaap:PaymentsForRepurchaseOfEquity",
        "ifrs-full:PaymentsToAcquireOrRedeemEntitysShares",
    )),
    Metric("dps", "주당배당금", "flow", (
        "us-gaap:CommonStockDividendsPerShareDeclared",
        "us-gaap:CommonStockDividendsPerShareCashPaid",
    ), unit="per_share"),
    # --- banks
    Metric("net_interest_income", "순이자이익", "flow", (
        "us-gaap:InterestIncomeExpenseNet",
        "us-gaap:InterestIncomeExpenseAfterProvisionForLoanLoss",
        "ifrs-full:InterestRevenueExpense",
    )),
    Metric("noninterest_income", "비이자이익", "flow", ("us-gaap:NoninterestIncome",)),
    Metric("noninterest_expense", "비이자비용", "flow", ("us-gaap:NoninterestExpense",)),
    Metric("provision", "대손비용", "flow", (
        "us-gaap:ProvisionForLoanLeaseAndOtherLosses",
        "us-gaap:ProvisionForLoanAndLeaseLosses",
        "us-gaap:ProvisionForCreditLossesNet",
    )),
    Metric("deposits", "예수금", "instant", ("us-gaap:Deposits",)),
    # --- insurers
    Metric("premiums", "보험료 수익", "flow", (
        "us-gaap:PremiumsEarnedNet",
        "us-gaap:PremiumsEarnedNetPropertyAndCasualty",
        "us-gaap:PremiumsEarnedNetLife",
    )),
    # --- REITs (FFO = net income + depreciation + impairments - gains on property sales)
    Metric("re_gain", "부동산 처분이익", "flow", (
        "us-gaap:GainLossOnSaleOfProperties",
        "us-gaap:GainsLossesOnSalesOfInvestmentRealEstate",
        "us-gaap:GainLossOnSaleOfRealEstateInvestmentProperty",
        "us-gaap:GainLossOnDispositionOfRealEstateDiscontinuedOperations",
    )),
    Metric("re_impairment", "부동산 손상", "flow", (
        "us-gaap:ImpairmentOfRealEstate",
        "us-gaap:ImpairmentOfLongLivedAssetsHeldForUse",
    )),
    # --- cost structure (operating companies)
    Metric("cost_of_revenue", "매출원가", "flow", (
        "us-gaap:CostOfRevenue",
        "us-gaap:CostOfGoodsAndServicesSold",
        "us-gaap:CostOfGoodsSold",
        "us-gaap:CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization",
        "ifrs-full:CostOfSales",
    )),
    Metric("rnd", "연구개발비", "flow", (
        "us-gaap:ResearchAndDevelopmentExpense",
        "us-gaap:ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
        "ifrs-full:ResearchAndDevelopmentExpense",
    )),
    Metric("sga", "판매관리비", "flow", (
        "us-gaap:SellingGeneralAndAdministrativeExpense",
        "ifrs-full:SellingGeneralAndAdministrativeExpense",
    )),
    Metric("selling", "판매·마케팅비", "flow", (
        "us-gaap:SellingAndMarketingExpense",
        "us-gaap:SellingExpense",
        "ifrs-full:SellingExpense",
        "ifrs-full:DistributionCosts",
    )),
    Metric("gna", "일반관리비", "flow", (
        "us-gaap:GeneralAndAdministrativeExpense",
        "ifrs-full:AdministrativeExpense",
    )),
    Metric("current_assets", "유동자산", "instant", (
        "us-gaap:AssetsCurrent",
        "ifrs-full:CurrentAssets",
    )),
    Metric("current_liabilities", "유동부채", "instant", (
        "us-gaap:LiabilitiesCurrent",
        "ifrs-full:CurrentLiabilities",
    )),
)

# Shares outstanding from the filing cover page (dei); used for market cap.
SHARES_OUTSTANDING_CONCEPTS = ("dei:EntityCommonStockSharesOutstanding",)

METRIC_BY_KEY = {m.key: m for m in METRICS}
ALL_CONCEPTS: frozenset[str] = frozenset(
    [c for m in METRICS for c in m.concepts] + list(SHARES_OUTSTANDING_CONCEPTS))

# Labels for derived columns, used by the UI.
DERIVED_LABELS = {
    "fcf": "잉여현금흐름(FCF)",
    "gross_margin": "매출총이익률",
    "operating_margin": "영업이익률",
    "net_margin": "순이익률",
    "debt_ratio": "부채비율",
    "debt": "총차입금",
    "debt_long": "장기차입금(유동성 포함)",
    "debt_short": "단기차입금",
    "lease": "리스부채",
    "de_ratio": "D/E (차입금/자본)",
    "de_ratio_lease": "D/E (리스 포함)",
    "net_debt": "순차입금",
    "fcf_margin": "FCF 마진",
    "roe": "ROE",
    "roic": "ROIC",
    "roa": "ROA",
    "ebitda": "EBITDA",
    "ebitda_margin": "EBITDA 마진",
    "current_ratio": "유동비율",
    "interest_coverage": "이자보상배율",
    "net_debt_ebitda": "순차입금/EBITDA",
    "payout_ratio": "배당성향",
    "equity_ratio": "자기자본비율",
    "efficiency_ratio": "효율성 비율",
    "ffo": "FFO(추정)",
    "ffo_per_share": "주당 FFO(추정)",
}

_ANNUAL_DAYS = (330, 400)
_QUARTER_DAYS = (80, 100)


def prepare_facts(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only the concepts we use, with parsed dates and numeric values."""
    cols = ["concept", "unit", "period_type", "period_start", "period_end",
            "numeric_value", "filing_date", "form_type"]
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)
    out = df.loc[df["concept"].isin(ALL_CONCEPTS) & df["numeric_value"].notna(), cols].copy()
    for c in ("period_start", "period_end", "filing_date"):
        out[c] = pd.to_datetime(out[c], errors="coerce")
    return out.dropna(subset=["period_end"])


def detect_currency(facts: pd.DataFrame) -> str:
    """Reporting currency: the most common unit among revenue / net income facts."""
    keys = METRIC_BY_KEY["revenue"].concepts + METRIC_BY_KEY["net_income"].concepts
    units = facts.loc[facts["concept"].isin(keys), "unit"]
    units = units[~units.str.contains("share", case=False, na=False)]
    if units.empty:
        return "USD"
    return str(units.value_counts().idxmax())


def _unit_ok(units: pd.Series, currency: str, kind: str) -> pd.Series:
    if kind == "per_share":
        return units.str.startswith(currency) & units.str.contains("share", case=False)
    if kind == "shares":
        return units == "shares"
    return units == currency


def _latest_filed(sub: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """For facts reported several times (later filings restate), keep the latest filing."""
    return (sub.sort_values("filing_date", na_position="first")
               .drop_duplicates(subset=keys, keep="last"))


def _flow_series(sub: pd.DataFrame, period: Period) -> pd.Series:
    sub = sub.dropna(subset=["period_start"])
    if sub.empty:
        return pd.Series(dtype=float)
    # Earliest filing of each period = as originally reported. Used for derived quarters:
    # subtracting an original 9-month YTD from a full year restated years later mixes bases
    # (FRO FY2013 was restated from $517M to $134M, giving Q4 revenue of -$240M).
    original = (sub.sort_values("filing_date", na_position="last")
                   .drop_duplicates(subset=["period_start", "period_end"], keep="first").copy())
    original["days"] = (original["period_end"] - original["period_start"]).dt.days
    if period == "annual":
        lo, hi = _ANNUAL_DAYS
        a = sub.assign(days=(sub["period_end"] - sub["period_start"]).dt.days)
        a = a[(a["days"] >= lo) & (a["days"] <= hi)]
        # Twelve-month figures inside 10-Qs (AMZN reports trailing-twelve-month results there)
        # are not fiscal years: keep annual-report facts. This must happen *before* picking the
        # latest filing, because the latest copy of a fiscal year is often in another form
        # (an 8-K recast, or the proxy's pay-versus-performance table for net income).
        annual_form = a["form_type"].fillna("").str.match(r"^(10-K|20-F|40-F|10-KT)")
        if annual_form.any():
            a = a[annual_form]
        a = _latest_filed(a, ["period_start", "period_end"])
        a = a.sort_values("days").drop_duplicates("period_end", keep="last")
        return a.set_index("period_end")["numeric_value"].sort_index()

    sub = _latest_filed(sub, ["period_start", "period_end"]).copy()
    sub["days"] = (sub["period_end"] - sub["period_start"]).dt.days
    lo, hi = _QUARTER_DAYS
    direct = sub[(sub["days"] >= lo) & (sub["days"] <= hi)]
    result = direct.drop_duplicates("period_end", keep="last").set_index("period_end")["numeric_value"]

    # Cash-flow items (and Q4 in general) are only reported year-to-date. Derive the
    # discrete quarter as YTD(end) - YTD(previous end) for facts sharing a start date.
    derived: dict[pd.Timestamp, float] = {}
    for _, grp in original.groupby("period_start"):
        grp = grp.sort_values("period_end")
        ends = grp["period_end"].tolist()
        vals = grp["numeric_value"].tolist()
        for j in range(len(ends)):
            for i in range(j):
                gap = (ends[j] - ends[i]).days
                if lo <= gap <= hi:
                    derived.setdefault(ends[j], vals[j] - vals[i])
    if derived:
        result = result.combine_first(pd.Series(derived, dtype=float))
    return result.sort_index()


def _instant_series(sub: pd.DataFrame) -> pd.Series:
    if sub.empty:
        return pd.Series(dtype=float)
    sub = _latest_filed(sub, ["period_end"])
    return sub.set_index("period_end")["numeric_value"].sort_index()


# Amounts that cannot be negative; a negative value can only come from a broken derivation.
NON_NEGATIVE = frozenset({"cost_of_revenue", "rnd", "sga", "selling", "gna", "revenue", "capex", "da", "dividends", "buybacks", "dps", "shares_diluted",
                          "premiums", "interest_expense", "_dep", "_amort", "deposits"})


def metric_series(facts: pd.DataFrame, metric: Metric, period: Period, currency: str) -> pd.Series:
    merged = _metric_series(facts, metric, period, currency)
    if metric.key in NON_NEGATIVE and not merged.empty:
        merged = merged.where(merged >= 0)
    return merged


def _metric_series(facts: pd.DataFrame, metric: Metric, period: Period, currency: str) -> pd.Series:
    merged = pd.Series(dtype=float)
    for concept in metric.concepts:
        sub = facts[(facts["concept"] == concept)
                    & _unit_ok(facts["unit"], currency, metric.unit)]
        if sub.empty:
            continue
        s = _flow_series(sub, period) if metric.kind == "flow" else _instant_series(sub)
        merged = s if merged.empty else merged.combine_first(s)
    return merged


def turnaround(latest: float | None, prev: float | None) -> str | None:
    """Word for a year-over-year change whose percentage would be meaningless."""
    if latest is None or prev is None or pd.isna(latest) or pd.isna(prev):
        return None
    if prev > 0 and latest < 0:
        return "적자전환"
    if prev < 0 and latest > 0:
        return "흑자전환"
    if prev < 0 and latest < 0:
        return "적자지속" if latest <= prev else "적자축소"
    return None


def yoy_prev(table: pd.DataFrame, col: str, period: Period) -> float | None:
    """The same period a year earlier (previous row for annual, four rows back otherwise)."""
    if table.empty or col not in table:
        return None
    lag = 1 if period == "annual" else 4
    if len(table) <= lag:
        return None
    v = table[col].iloc[-1 - lag]
    return None if pd.isna(v) else float(v)


def yoy(table: pd.DataFrame, col: str, period: Period) -> tuple[float | None, float | None]:
    """(latest value, change vs the same period a year earlier).

    Annual compares with the previous row; quarterly and TTM with four rows back.
    """
    if table.empty or col not in table:
        return None, None
    s = table[col]
    if s.dropna().empty:
        return None, None
    latest = s.iloc[-1]
    if pd.isna(latest):
        return None, None
    lag = 1 if period == "annual" else 4
    if len(s) <= lag or pd.isna(s.iloc[-1 - lag]) or s.iloc[-1 - lag] == 0:
        return float(latest), None
    prev = float(s.iloc[-1 - lag])
    if prev < 0 or latest < 0:  # a % change across or below zero means nothing: see turnaround()
        return float(latest), None
    return float(latest), (float(latest) - prev) / abs(prev)


def period_label(end: pd.Timestamp, period: Period) -> str:
    # 52/53-week fiscal years can end in the first days of January; label them with
    # the year they mostly cover.
    if period == "annual":
        return f"FY{(end - pd.Timedelta(days=7)).year % 100:02d}"
    return f"{end.year % 100:02d}.{end.month:02d}"


def build_table(raw_facts: pd.DataFrame, period: Period = "annual", n: int = 8) -> tuple[pd.DataFrame, str]:
    """Return (table, currency). Table: one row per period, oldest first.

    Columns: label, one per metric key, plus derived fcf / margins / debt_ratio.
    """
    facts = prepare_facts(raw_facts)
    currency = detect_currency(facts) if not facts.empty else "USD"
    if facts.empty:
        return pd.DataFrame(), currency

    if period == "ttm":
        table = _ttm_table(_raw_table(facts, "quarterly", currency))
    else:
        table = _raw_table(facts, period, currency)
    if table.empty:
        return pd.DataFrame(), currency
    if period != "annual":
        # Quarterly history that stopped long before the latest annual report (a company that
        # moved to half-year 6-K reports, e.g. FRO stops in 2014) must not pass for current.
        annual = _raw_table(facts, "annual", currency)
        if not annual.empty and table.index.max() < annual.index.max() - pd.Timedelta(days=200):
            return pd.DataFrame(), currency
    # Derive on the full history first so averages (ROE, ROIC) have the prior period available.
    return _add_derived(table.copy(), period).tail(n), currency


def _raw_table(facts: pd.DataFrame, period: Period, currency: str) -> pd.DataFrame:
    """One row per period with every metric as reported (no derived columns)."""
    flows = {m.key: metric_series(facts, m, period, currency) for m in METRICS if m.kind == "flow"}
    anchor = flows["revenue"].index.union(flows["net_income"].index)
    if anchor.empty:
        anchor = pd.DatetimeIndex(sorted(set().union(*[s.index for s in flows.values()])))
    if anchor.empty:
        return pd.DataFrame()

    table = pd.DataFrame(index=pd.DatetimeIndex(anchor).sort_values())
    for key, s in flows.items():
        table[key] = s.reindex(table.index)
    for m in METRICS:
        if m.kind == "instant":
            table[m.key] = metric_series(facts, m, period, currency).reindex(table.index)

    # Annual periods older than gaps in reporting can produce stray rows (e.g. a
    # transition period); keep rows that carry at least revenue or net income.
    return table[table[["revenue", "net_income"]].notna().any(axis=1)]


# Flow metrics that are summed over four quarters for TTM. Share counts are averages, not
# sums, so TTM uses the latest quarter's value for those.
_TTM_SUM = tuple(m.key for m in METRICS if m.kind == "flow" and m.unit != "shares")


def _ttm_table(quarterly: pd.DataFrame) -> pd.DataFrame:
    """Rolling four-quarter sums at every quarter end.

    A value is kept only when all four quarters exist and are consecutive (~3 months apart);
    otherwise it would silently mix in a missing quarter as zero.
    """
    if quarterly.empty or len(quarterly) < 4:
        return pd.DataFrame()
    q = quarterly.copy()
    gaps = pd.Series(q.index, index=q.index).diff().dt.days
    ok_gap = gaps.between(*_QUARTER_DAYS)
    contiguous = ok_gap.rolling(3, min_periods=3).sum().eq(3)  # the 3 gaps inside the window
    for col in _TTM_SUM:
        rolled = q[col].rolling(4, min_periods=4).sum()
        q[col] = rolled.where(contiguous)
    return q[q[["revenue", "net_income"]].notna().any(axis=1)]


def _sum_known(*cols: pd.Series) -> pd.Series:
    """Row-wise sum treating missing as 0, but NaN where every part is missing."""
    frame = pd.concat(cols, axis=1)
    return frame.sum(axis=1, min_count=1)


def _debt_columns(table: pd.DataFrame) -> None:
    """Total borrowings (debt_long + debt_short = debt) and lease liabilities.

    Companies tag debt in incompatible ways, verified against 10-K balance sheets:
      - AAPL: LongTermDebt (incl. current portion) + CommercialPaper
      - MCD:  LongTermDebt tagged *without* the current portion, plus LongTermDebtCurrent
      - KO:   LongTermDebtAndCapitalLeaseObligations(+Current) + CommercialPaper + Other
      - NVDA: LongTermDebtNoncurrent + LongTermDebtCurrent (DebtCurrent = the same current part)
      - O (REIT): NotesPayable + LoansPayable + SecuredDebt + CommercialPaper, no LongTermDebt
    Long-term debt is therefore the larger of the "total" tag and noncurrent + current, and
    DebtCurrent is only used when the current portion is not tagged separately.
    """
    t = table
    parts = _sum_known(t["_ltd_noncurrent"], t["_ltd_current"]).where(t["_ltd_noncurrent"].notna())
    ltd = pd.concat([t["_ltd_total"], parts], axis=1).max(axis=1)  # max ignores NaN
    st = t["_st_borrowings"].combine_first(_sum_known(t["_commercial_paper"], t["_other_st"]))

    # NVDA-style: noncurrent tagged, current only as DebtCurrent (which already includes
    # short-term borrowings).
    use_debt_current = t["_ltd_total"].isna() & t["_ltd_current"].isna() & t["_debt_current"].notna()
    ltd = ltd.where(~use_debt_current, t["_ltd_noncurrent"])
    st = st.where(~use_debt_current, t["_debt_current"])

    # IFRS bonds + long-term bank borrowings, when the US-GAAP-style tags are absent.
    ifrs = _sum_known(t["_bonds_noncurrent"], t["_bonds_current"], t["_ifrs_lt_borrowings"])
    ltd = ltd.combine_first(ifrs)

    # REIT-style: no long-term-debt tags at all.
    other = _sum_known(t["_notes_payable"], t["_loans_payable"], t["_secured_debt"],
                       t["_unsecured_debt"], t["_credit_line"])
    ltd = ltd.combine_first(other)

    t["debt_long"] = ltd
    t["debt_short"] = st
    t["debt"] = _sum_known(ltd, st)
    t["lease"] = _sum_known(t["_op_lease"], t["_fin_lease"])


def _add_derived(table: pd.DataFrame, period: Period) -> pd.DataFrame:
    """Margins, FCF, leverage and return ratios. ``table`` holds reported metrics."""
    rev = table["revenue"].where(table["revenue"] != 0)
    table["fcf"] = table["ocf"] - table["capex"].fillna(0)
    table.loc[table["ocf"].isna(), "fcf"] = np.nan
    table["gross_margin"] = table["gross_profit"] / rev
    table["operating_margin"] = table["operating_income"] / rev
    table["net_margin"] = table["net_income"] / rev
    if table["liabilities"].isna().all():
        table["liabilities"] = table["assets"] - table["equity"]
    eq = table["equity"].where(table["equity"] > 0)
    table["debt_ratio"] = table["liabilities"] / eq
    table["fcf_margin"] = table["fcf"] / rev
    _debt_columns(table)
    table["da"] = table["da"].combine_first(_sum_known(table["_dep"], table["_amort"]))
    table["net_debt"] = table["debt"] - table["cash"].fillna(0)  # unknown when debt is untagged
    table["de_ratio"] = table["debt"] / eq
    table["de_ratio_lease"] = (table["debt"] + table["lease"].fillna(0)) / eq
    table["ebitda"] = table["operating_income"] + table["da"]  # NaN when D&A is not tagged
    table["ebitda_margin"] = table["ebitda"] / rev
    table["current_ratio"] = table["current_assets"] / table["current_liabilities"].where(
        table["current_liabilities"] > 0)
    table["interest_coverage"] = table["operating_income"] / table["interest_expense"].where(
        table["interest_expense"] > 0)
    table["payout_ratio"] = table["dividends"] / table["net_income"].where(table["net_income"] > 0)
    table["equity_ratio"] = table["equity"] / table["assets"].where(table["assets"] > 0)
    table["efficiency_ratio"] = table["noninterest_expense"] / rev
    # FFO (NAREIT-style estimate): only meaningful for REITs; needs net income and D&A.
    table["ffo"] = (table["net_income"] + table["da"] + table["re_impairment"].fillna(0)
                    - table["re_gain"].fillna(0))
    table["ffo_per_share"] = table["ffo"] / table["shares_diluted"].where(table["shares_diluted"] > 0)
    if period in ("annual", "ttm"):
        # Twelve months of flows: returns use average capital over that year (one row back
        # for annual, four quarters back for TTM); the earliest rows fall back to period-end.
        lag = 1 if period == "annual" else 4

        def avg(col_values: pd.Series) -> pd.Series:
            return ((col_values + col_values.shift(lag)) / 2).fillna(col_values)

        table["net_debt_ebitda"] = table["net_debt"] / table["ebitda"].where(table["ebitda"] > 0)
        avg_assets = avg(table["assets"])
        table["roa"] = table["net_income"] / avg_assets.where(avg_assets > 0)
        avg_eq = avg(table["equity"])
        table["roe"] = table["net_income"] / avg_eq.where(avg_eq > 0)
        tax_rate = (table["income_tax"] / table["pretax_income"].where(table["pretax_income"] > 0)).clip(0, 0.5)
        nopat = table["operating_income"] * (1 - tax_rate.fillna(0.21))
        invested = table["equity"] + table["debt"].fillna(0) - table["cash"].fillna(0)
        avg_inv = avg(invested)
        table["roic"] = nopat / avg_inv.where(avg_inv > 0)
    else:
        for col in ("roe", "roic", "roa", "net_debt_ebitda"):
            table[col] = np.nan

    table.insert(0, "label", [period_label(d, period) for d in table.index])
    table.index.name = "period_end"
    return table


def change(table: pd.DataFrame, col: str) -> tuple[float | None, float | None]:
    """(latest value, relative change vs previous row) for a column."""
    if table.empty or col not in table:
        return None, None
    s = table[col].dropna()
    if s.empty:
        return None, None
    latest = float(s.iloc[-1])
    if len(s) < 2 or s.iloc[-2] == 0:
        return latest, None
    prev = float(s.iloc[-2])
    return latest, (latest - prev) / abs(prev)


def cagr(table: pd.DataFrame, col: str, years: int, rows_per_year: int = 1) -> float | None:
    """Compound annual growth over ``years``; None if not computable.

    ``rows_per_year`` is 1 for annual tables and 4 for quarterly-spaced TTM tables.
    """
    if table.empty or col not in table:
        return None
    s = table[col]
    steps = years * rows_per_year
    if len(s) <= steps or pd.isna(s.iloc[-1]) or pd.isna(s.iloc[-1 - steps]):
        return None
    start, end = float(s.iloc[-1 - steps]), float(s.iloc[-1])
    if start <= 0 or end <= 0:
        return None
    return (end / start) ** (1 / years) - 1


TTM_FLOWS = ("revenue", "gross_profit", "operating_income", "net_income", "eps", "ocf", "capex", "fcf",
             "da", "ebitda", "interest_expense", "dividends", "buybacks", "dps", "ffo",
             "net_interest_income", "noninterest_expense", "provision", "premiums")


def ttm(quarterly: pd.DataFrame, offset: int = 0) -> dict | None:
    """Sum of four consecutive quarters for flow metrics: the latest four, or with
    ``offset=4`` the four before those (for year-over-year TTM comparison).

    Returns None when those quarters are not contiguous (e.g. missing filings).
    """
    if quarterly is None or len(quarterly) < 4 + offset:
        return None
    end = len(quarterly) - offset
    last4 = quarterly.iloc[end - 4:end]
    gaps = pd.Series(last4.index).diff().dt.days.dropna()
    if not gaps.between(80, 100).all():
        return None
    out = {"label": f"TTM ({last4['label'].iloc[-1]})", "end": last4.index[-1]}
    for col in TTM_FLOWS:
        vals = last4[col]
        out[col] = float(vals.sum()) if vals.notna().all() else None
    return out


def latest_shares_outstanding(raw_facts: pd.DataFrame) -> float | None:
    """Latest cover-page shares outstanding. Multi-class companies report one value per
    class on the same date, so values sharing the latest date are summed."""
    if raw_facts is None or raw_facts.empty:
        return None
    sub = raw_facts[raw_facts["concept"].isin(SHARES_OUTSTANDING_CONCEPTS) & raw_facts["numeric_value"].notna()]
    if sub.empty:
        return None
    sub = sub.assign(period_end=pd.to_datetime(sub["period_end"]), filing_date=pd.to_datetime(sub["filing_date"]))
    latest_end = sub["period_end"].max()
    same = sub[sub["period_end"] == latest_end]
    same = same[same["filing_date"] == same["filing_date"].max()]
    return float(same["numeric_value"].drop_duplicates().sum())


VALUATION_KEYS = ("per", "psr", "pbr", "p_fcf", "p_ffo", "ffo_payout", "fcf_yield", "ev", "ev_ebit",
                  "ev_ebitda", "ev_sales",
                  "peg", "eps", "eps_growth", "bps", "dps", "dividend_yield", "buyback_yield",
                  "shareholder_yield", "payout_ratio", "shares")


def valuation(market_cap: float | None, flows: dict | None, balance: pd.Series | None, *,
              price: float | None = None, prev_flows: dict | None = None,
              eps_cagr: float | None = None) -> dict:
    """Valuation multiples and per-share figures.

    ``flows`` are trailing-twelve-month sums (or the latest fiscal year), ``prev_flows`` the
    twelve months before that, ``eps_cagr`` a multi-year EPS growth rate used for PEG.
    """
    out = {k: None for k in VALUATION_KEYS}
    if not market_cap or market_cap <= 0 or not flows:
        return out

    def ratio(num, den, positive_den=True):
        if num is None or den is None or pd.isna(num) or pd.isna(den):
            return None
        if positive_den and den <= 0:
            return None
        return num / den

    out["per"] = ratio(market_cap, flows.get("net_income"))
    out["psr"] = ratio(market_cap, flows.get("revenue"))
    out["fcf_yield"] = ratio(flows.get("fcf"), market_cap)
    if balance is not None:
        out["pbr"] = ratio(market_cap, balance.get("equity"))
        debt = balance.get("debt")
        cash = balance.get("cash")
        out["ev"] = market_cap + (0 if debt is None or pd.isna(debt) else debt) - (0 if cash is None or pd.isna(cash) else cash)
        out["ev_ebit"] = ratio(out["ev"], flows.get("operating_income"))
        out["ev_ebitda"] = ratio(out["ev"], flows.get("ebitda"))
        out["ev_sales"] = ratio(out["ev"], flows.get("revenue"))
    out["p_fcf"] = ratio(market_cap, flows.get("fcf"))
    out["p_ffo"] = ratio(market_cap, flows.get("ffo"))
    if flows.get("dividends") is not None:
        out["ffo_payout"] = ratio(flows.get("dividends"), flows.get("ffo"))

    out["eps"] = flows.get("eps")
    if prev_flows and out["eps"] is not None:
        prev_eps = prev_flows.get("eps")
        if prev_eps is not None and prev_eps > 0:
            out["eps_growth"] = out["eps"] / prev_eps - 1
    if out["per"] and eps_cagr and eps_cagr > 0:
        out["peg"] = out["per"] / (eps_cagr * 100)

    shares = market_cap / price if price else None
    out["shares"] = shares
    if shares and balance is not None:
        out["bps"] = ratio(balance.get("equity"), shares, positive_den=True)
    dividends, buybacks = flows.get("dividends"), flows.get("buybacks")
    out["dps"] = flows.get("dps") or (ratio(dividends, shares) if shares else None)
    # Missing tags stay None ("–"), not 0%: an untagged quarter is not proof of no dividend.
    out["dividend_yield"] = ratio(dividends, market_cap)
    out["buyback_yield"] = ratio(buybacks, market_cap)
    if out["dividend_yield"] is not None or out["buyback_yield"] is not None:
        out["shareholder_yield"] = (out["dividend_yield"] or 0) + (out["buyback_yield"] or 0)
    out["payout_ratio"] = ratio(dividends, flows.get("net_income")) if dividends is not None else None
    return out


def historical_per(annual: pd.DataFrame, prices: pd.Series) -> pd.DataFrame:
    """PER at each fiscal year end: closing price on/just before period end ÷ diluted EPS."""
    if annual.empty or prices is None or prices.empty:
        return pd.DataFrame(columns=["label", "price", "eps", "per"])
    prices = prices.sort_index()
    rows = []
    for end, row in annual.iterrows():
        before = prices[prices.index <= end]
        if before.empty or (end - before.index[-1]).days > 10:
            continue
        price = float(before.iloc[-1])
        eps = row.get("eps")
        per = price / eps if eps is not None and pd.notna(eps) and eps > 0 else None
        rows.append({"label": row["label"], "price": price, "eps": eps, "per": per})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- dividend history
def dividend_history(payments: pd.Series, prices: pd.Series | None = None,
                     today: pd.Timestamp | None = None) -> dict:
    """Summarise per-payment dividends (indexed by ex-date).

    Returns {"annual": DataFrame, "payments": Series, ...stats}. ``annual`` has one row per
    calendar year: dps (sum of payments), count, growth vs previous year, yield (dps ÷
    year-end price, or latest price for the running year) and ``partial`` for the running
    year, which is excluded from growth and streak statistics.
    """
    today = pd.Timestamp(today or pd.Timestamp.today()).normalize()
    if payments is None or payments.empty:
        return {"annual": pd.DataFrame(), "payments": pd.Series(dtype=float)}
    payments = payments.sort_index()
    by_year = payments.groupby(payments.index.year)
    annual = pd.DataFrame({"dps": by_year.sum(), "count": by_year.size()})
    annual.index.name = "year"
    annual["partial"] = annual.index == today.year

    full = annual[~annual["partial"]]
    annual["growth"] = full["dps"].pct_change()
    if prices is not None and not prices.empty:
        year_end = prices.groupby(prices.index.year).last()
        annual["yield"] = annual["dps"] / year_end.reindex(annual.index)
        if annual["partial"].any():  # running year: trailing-12-month payments ÷ latest price
            ttm_dps = payments[payments.index > today - pd.DateOffset(years=1)].sum()
            annual.loc[annual["partial"], "yield"] = ttm_dps / float(prices.iloc[-1])
    else:
        annual["yield"] = np.nan

    # Streaks count back from the last complete year, without gaps in the calendar.
    years = list(full.index)
    paid_streak = 0
    for i in range(len(years) - 1, -1, -1):
        if i < len(years) - 1 and years[i] != years[i + 1] - 1:
            break
        paid_streak += 1
    # Raises are judged on the average payment per year. The yearly sum (what dividend lists
    # nominally use) is distorted when an ex-date slips across New Year and a year gets 3 or 5
    # payments (KO showed 23 instead of 63 years); the median misses years where the raise
    # landed in the last payment only (MSFT 2009, PG 1985). The mean handles both.
    # Payments more than 40% away from the year's median are dropped first: specials and
    # data errors in Yahoo's history (KO 2001 has a doubled payment, PG 2002 a stray 0.345,
    # PG 1983 a halved one) would otherwise fake a cut the next year.
    med = payments.groupby(payments.index.year).transform("median")
    regular = payments[(payments / med - 1).abs() <= 0.4]
    rate = regular.groupby(regular.index.year).mean().reindex(full.index)
    raise_streak = 0
    for i in range(len(years) - 1, 0, -1):
        if years[i] - 1 != years[i - 1] or rate.iloc[i] <= rate.iloc[i - 1] * 1.0001:
            break
        raise_streak += 1
    if not years or years[-1] < today.year - 1:  # stopped paying: no current streak
        paid_streak = raise_streak = 0

    recent_full = full.tail(3)
    per_year = int(round(recent_full["count"].median())) if len(recent_full) else None
    ttm = float(payments[payments.index > today - pd.DateOffset(years=1)].sum())

    def growth_rate(years_back: int):
        if len(full) <= years_back:
            return None
        start, end = float(full["dps"].iloc[-1 - years_back]), float(full["dps"].iloc[-1])
        return (end / start) ** (1 / years_back) - 1 if start > 0 and end > 0 else None

    return {
        "annual": annual,
        "payments": payments,
        "last_date": payments.index[-1],
        "last_amount": float(payments.iloc[-1]),
        "ttm_dps": ttm,
        "per_year": per_year,
        "paid_streak": paid_streak,
        "raise_streak": raise_streak,
        "cagr5": growth_rate(5),
        "cagr10": growth_rate(10),
        "first_year": int(annual.index[0]),
    }


def table_from_raw(raw: pd.DataFrame, period: Period, n: int = 12) -> pd.DataFrame:
    """Build a dashboard table from an already-assembled quarterly frame (metric-key columns),
    e.g. Yahoo quarterly financials. Same TTM and derived logic as SEC data."""
    if raw is None or raw.empty:
        return pd.DataFrame()
    table = pd.DataFrame(index=pd.DatetimeIndex(raw.index).sort_values())
    for m in METRICS:
        table[m.key] = raw[m.key].reindex(table.index) if m.key in raw else np.nan
    table = table[table[["revenue", "net_income"]].notna().any(axis=1)]
    if period == "ttm":
        table = _ttm_table(table)
    if table.empty:
        return pd.DataFrame()
    return _add_derived(table.copy(), "quarterly" if period == "quarterly" else "ttm").tail(n)


# ---------------------------------------------------------------- cost structure
def cost_structure(row: pd.Series) -> dict | None:
    """Where each unit of revenue goes, for one period (a row of a table).

    revenue = cost of revenue + R&D + SG&A + other operating costs + operating income.
    SG&A falls back to selling + G&A when only those are tagged (MSFT); cost of revenue falls
    back to revenue - gross profit. Whatever the standard tags do not cover becomes "기타
    영업비용" so the parts always add up to revenue (AMZN tags fulfillment etc. with its own
    names). Returns {"parts": Series (label -> amount), "base": revenue or total cost,
    "loss": bool, "exact": bool} or None.
    """
    rev = row.get("revenue")
    opi = row.get("operating_income")
    if rev is None or pd.isna(rev) or rev <= 0 or opi is None or pd.isna(opi):
        return None

    def val(key):
        v = row.get(key)
        return None if v is None or pd.isna(v) else float(v)

    cogs = val("cost_of_revenue")
    if cogs is None and val("gross_profit") is not None:
        cogs = rev - val("gross_profit")
    sga = val("sga")
    if sga is None and (val("selling") is not None or val("gna") is not None):
        sga = (val("selling") or 0.0) + (val("gna") or 0.0)
    parts = {"매출원가": cogs, "연구개발비": val("rnd"), "판매관리비": sga}
    parts = {k: v for k, v in parts.items() if v is not None and v > 0}
    if not parts:
        return None
    total_cost = rev - opi
    other = total_cost - sum(parts.values())
    exact = True
    if other > 0.005 * rev:
        parts["기타 영업비용"] = other
    elif other < -0.01 * rev:
        exact = False  # tags overlap (e.g. R&D also inside SG&A): shares of the parts only
    if opi > 0:
        parts["영업이익"] = float(opi)
        base = float(rev)
    else:
        base = sum(parts.values())
    return {"parts": pd.Series(parts, dtype=float), "base": base, "loss": opi <= 0, "exact": exact}
