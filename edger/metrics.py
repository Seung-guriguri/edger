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

Period = Literal["annual", "quarterly"]


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    kind: Literal["flow", "instant"]  # flow = duration (P&L, cash flow), instant = balance sheet
    concepts: tuple[str, ...]
    per_share: bool = False


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
    ), per_share=True),
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
)

METRIC_BY_KEY = {m.key: m for m in METRICS}
ALL_CONCEPTS: frozenset[str] = frozenset(c for m in METRICS for c in m.concepts)

# Labels for derived columns, used by the UI.
DERIVED_LABELS = {
    "fcf": "잉여현금흐름(FCF)",
    "gross_margin": "매출총이익률",
    "operating_margin": "영업이익률",
    "net_margin": "순이익률",
    "debt_ratio": "부채비율",
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


def _unit_ok(units: pd.Series, currency: str, per_share: bool) -> pd.Series:
    if per_share:
        return units.str.startswith(currency) & units.str.contains("share", case=False)
    return units == currency


def _latest_filed(sub: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """For facts reported several times (later filings restate), keep the latest filing."""
    return (sub.sort_values("filing_date", na_position="first")
               .drop_duplicates(subset=keys, keep="last"))


def _flow_series(sub: pd.DataFrame, period: Period) -> pd.Series:
    sub = sub.dropna(subset=["period_start"])
    if sub.empty:
        return pd.Series(dtype=float)
    sub = _latest_filed(sub, ["period_start", "period_end"]).copy()
    sub["days"] = (sub["period_end"] - sub["period_start"]).dt.days

    if period == "annual":
        lo, hi = _ANNUAL_DAYS
        a = sub[(sub["days"] >= lo) & (sub["days"] <= hi)]
        a = a.sort_values("days").drop_duplicates("period_end", keep="last")
        return a.set_index("period_end")["numeric_value"].sort_index()

    lo, hi = _QUARTER_DAYS
    direct = sub[(sub["days"] >= lo) & (sub["days"] <= hi)]
    result = direct.drop_duplicates("period_end", keep="last").set_index("period_end")["numeric_value"]

    # Cash-flow items (and Q4 in general) are only reported year-to-date. Derive the
    # discrete quarter as YTD(end) - YTD(previous end) for facts sharing a start date.
    derived: dict[pd.Timestamp, float] = {}
    for _, grp in sub.groupby("period_start"):
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


def metric_series(facts: pd.DataFrame, metric: Metric, period: Period, currency: str) -> pd.Series:
    merged = pd.Series(dtype=float)
    for concept in metric.concepts:
        sub = facts[(facts["concept"] == concept)
                    & _unit_ok(facts["unit"], currency, metric.per_share)]
        if sub.empty:
            continue
        s = _flow_series(sub, period) if metric.kind == "flow" else _instant_series(sub)
        merged = s if merged.empty else merged.combine_first(s)
    return merged


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

    flows = {m.key: metric_series(facts, m, period, currency) for m in METRICS if m.kind == "flow"}
    anchor = flows["revenue"].index.union(flows["net_income"].index)
    if anchor.empty:
        anchor = pd.DatetimeIndex(sorted(set().union(*[s.index for s in flows.values()])))
    if anchor.empty:
        return pd.DataFrame(), currency

    table = pd.DataFrame(index=pd.DatetimeIndex(anchor).sort_values())
    for key, s in flows.items():
        table[key] = s.reindex(table.index)
    for m in METRICS:
        if m.kind == "instant":
            table[m.key] = metric_series(facts, m, period, currency).reindex(table.index)

    # Annual periods older than gaps in reporting can produce stray rows (e.g. a
    # transition period); keep rows that carry at least revenue or net income.
    table = table[table[["revenue", "net_income"]].notna().any(axis=1)]
    table = table.tail(n).copy()

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

    table.insert(0, "label", [period_label(d, period) for d in table.index])
    table.index.name = "period_end"
    return table, currency


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
