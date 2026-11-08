"""What a company does and where its revenue comes from, from the latest annual report.

Revenue by business segment, by product/service and by geography is only in the filing's
XBRL as *dimensional* facts (the company-facts API leaves dimensions out), so the latest
10-K / 20-F XBRL is read directly.

Companies tag these breakdowns with parents and children side by side (AAPL: "Products"
next to iPhone, Mac, iPad...). For each breakdown the most detailed set of members whose
sum matches total revenue is used, so shares add up to 100%.
"""
from __future__ import annotations

import itertools

import pandas as pd

REVENUE_CONCEPTS = (
    "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
    "us-gaap:Revenues",
    "us-gaap:RevenueFromContractWithCustomerIncludingAssessedTax",
    "us-gaap:SalesRevenueNet",
    "ifrs-full:Revenue",
    "ifrs-full:RevenueFromContractsWithCustomers",
)
OPERATING_INCOME_CONCEPTS = ("us-gaap:OperatingIncomeLoss", "ifrs-full:ProfitLossFromOperatingActivities")

# breakdown key -> (Korean title, candidate axes)
AXES = {
    "segment": ("사업부문", ("us-gaap_StatementBusinessSegmentsAxis", "ifrs-full_SegmentsAxis")),
    "product": ("제품·서비스", ("srt_ProductOrServiceAxis", "ifrs-full_ProductsAndServicesAxis")),
    "geo": ("지역", ("srt_StatementGeographicalAxis", "ifrs-full_GeographicalAreasAxis")),
}
# A second dimension that only says "this is the operating-segment view" is harmless.
_HARMLESS = {("srt_ConsolidationItemsAxis", "us-gaap:OperatingSegmentsMember"),
             ("ifrs-full_SegmentConsolidationItemsAxis", "ifrs-full:OperatingSegmentsMember")}
_ANNUAL_DAYS = (330, 400)
_TOLERANCE = 0.015
_MAX_MEMBERS = 16  # subset search is exponential; companies rarely report more


def _annual(df: pd.DataFrame) -> pd.DataFrame:
    start = pd.to_datetime(df["period_start"], errors="coerce")
    end = pd.to_datetime(df["period_end"], errors="coerce")
    days = (end - start).dt.days
    out = df.assign(period_end=end)
    return out[(days >= _ANNUAL_DAYS[0]) & (days <= _ANNUAL_DAYS[1])]


def _single_axis(df: pd.DataFrame, axis_col: str, dim_cols: list[str]) -> pd.DataFrame:
    """Facts dimensioned by ``axis_col`` and nothing else (besides harmless markers)."""
    sub = df[df[axis_col].notna()]
    for col in dim_cols:
        if col == axis_col or col not in sub:
            continue
        axis = col.removeprefix("dim_")
        ok = [pd.isna(m) or (axis, m) in _HARMLESS for m in sub[col]]
        sub = sub[ok]
    return sub


def pick_members(values: pd.Series, total: float) -> tuple[list[str], bool]:
    """The largest set of members whose sum is within tolerance of ``total``.

    Returns (members, exact). When no subset matches, returns all members whose sum does not
    exceed the total (the remainder becomes "기타"), with exact=False.
    """
    values = values.dropna()
    values = values[values > 0]
    if values.empty or not total or total <= 0:
        return [], False
    names = list(values.sort_values(ascending=False).index[:_MAX_MEMBERS])
    for size in range(len(names), 0, -1):
        for combo in itertools.combinations(names, size):
            if abs(values[list(combo)].sum() - total) <= _TOLERANCE * total:
                return list(combo), True
    # No exact cover (e.g. "U.S." and "Other countries" only): keep the biggest members that fit.
    kept, running = [], 0.0
    for name in names:
        if running + values[name] <= total * (1 + _TOLERANCE):
            kept.append(name)
            running += values[name]
    return kept, False


def breakdowns(xbrl_facts: pd.DataFrame) -> dict:
    """Revenue breakdowns from an XBRL facts frame (``XBRL.facts.to_dataframe()``).

    Returns {key: {"title", "values": DataFrame(member label x fiscal year end, oldest first),
    "share": Series (latest year), "growth": Series, "op_income": DataFrame | None,
    "exact": bool}} plus "_total": Series of consolidated revenue by year.
    """
    df = xbrl_facts
    if df is None or df.empty:
        return {}
    df = df[df["numeric_value"].notna()]
    dim_cols = [c for c in df.columns if c.startswith("dim_")]
    annual = _annual(df[df["period_type"] == "duration"])

    # Consolidated revenue (no dimensions) picks the revenue concept the company uses.
    plain = annual[~annual["is_dimensioned"].astype(bool)]
    concept, total = None, pd.Series(dtype=float)
    for c in REVENUE_CONCEPTS:
        t = plain[plain["concept"] == c].groupby("period_end")["numeric_value"].max()
        if not t.empty:
            concept, total = c, t.sort_index()
            break
    if concept is None:
        return {}

    out: dict = {"_total": total}
    rev = annual[annual["concept"].isin(REVENUE_CONCEPTS)]
    opi = annual[annual["concept"].isin(OPERATING_INCOME_CONCEPTS)]
    for key, (title, axes) in AXES.items():
        for axis in axes:
            col = f"dim_{axis}"
            if col not in df:
                continue
            facts = _single_axis(rev[rev["concept"] == concept], col, dim_cols)
            if facts.empty:  # some companies tag segment revenue with "Revenues" only
                facts = _single_axis(rev, col, dim_cols)
            if facts.empty:
                continue
            labels = _member_labels(facts, col, dim_cols)
            table = facts.pivot_table(index=col, columns="period_end", values="numeric_value", aggfunc="max")
            latest = total.index.max()
            if latest not in table.columns:
                continue
            members, exact = pick_members(table[latest], float(total[latest]))
            if len(members) < 2:
                continue
            values = table.loc[members].sort_values(latest, ascending=False)
            values.index = _unique([_clean_label(labels.get(m, ""), m) for m in values.index])
            remainder = float(total[latest]) - float(values[latest].sum())
            if not exact and remainder > _TOLERANCE * float(total[latest]):
                other = total.reindex(values.columns) - values.sum()
                values.loc["기타(미분류)"] = other.where(other > 0)
            values = values[sorted(values.columns)]
            share = values[latest] / float(total[latest])
            prev = sorted(values.columns)[-2] if len(values.columns) > 1 else None
            growth = (values[latest] / values[prev] - 1) if prev is not None else pd.Series(dtype=float)

            op = None
            op_facts = _single_axis(opi, col, dim_cols) if col in opi else pd.DataFrame()
            if not op_facts.empty:
                op_table = op_facts.pivot_table(index=col, columns="period_end", values="numeric_value", aggfunc="max")
                op_table = op_table.reindex([m for m in members if m in op_table.index])
                if not op_table.empty and latest in op_table.columns:
                    op_table.index = _unique([_clean_label(labels.get(m, ""), m) for m in op_table.index])
                    op = op_table[sorted(op_table.columns)]
            out[key] = {"title": title, "values": values, "share": share, "growth": growth,
                        "op_income": op, "exact": exact}
            break
    return out


def _member_labels(facts: pd.DataFrame, col: str, dim_cols: list[str]) -> dict:
    """Member -> display label. ``dimension_member_label`` describes the fact's *first*
    dimension, so it is only trusted on facts that carry this axis alone (AAPL tags segments
    together with "Operating segments", which would otherwise label every segment)."""
    others = [c for c in dim_cols if c != col and c in facts]
    alone = facts[facts[others].isna().all(axis=1)] if others else facts
    return alone.drop_duplicates(col).set_index(col)["dimension_member_label"].fillna("").to_dict()


def _unique(labels: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for lbl in labels:
        seen[lbl] = seen.get(lbl, 0) + 1
        out.append(lbl if seen[lbl] == 1 else f"{lbl} ({seen[lbl]})")
    return out


def _clean_label(label: str, member: str) -> str:
    label = (label or "").strip()
    if label:
        for suffix in (" [Member]", " Segment", " segment"):
            label = label.removesuffix(suffix)
        return label
    # fall back to the member name: "aapl:GreaterChinaSegmentMember" -> "Greater China"
    name = member.split(":")[-1].removesuffix("Member").removesuffix("Segment")
    return "".join(" " + ch if ch.isupper() and i else ch for i, ch in enumerate(name)).strip()


def overview(text: str | None, max_chars: int = 1400) -> str | None:
    """The opening paragraphs of 10-K Item 1 (skipping headings), for a quick read."""
    if not text:
        return None
    # Re-flow hard-wrapped lines (20-F text breaks lines mid-sentence, often with blank lines
    # between): keep appending until a line ends a sentence.
    paras, buf = [], ""
    for line in (ln.strip() for ln in text.replace("\r", "").split("\n")):
        if not line:
            continue
        ends_sentence = line.endswith((".", ":", ";", "!", "?", "”", '"', ")"))
        if len(line) < 60 and not ends_sentence:  # a heading ("Products", "Our History ...")
            if buf:
                paras.append(buf)
            paras.append(line)
            buf = ""
            continue
        if buf and not buf.endswith((".", ":", ";", "!", "?", "”", '"', ")")):
            buf = f"{buf} {line}"
        else:
            if buf:
                paras.append(buf)
            buf = line
    if buf:
        paras.append(buf)
    boilerplate = ("item ", "part i", "in this report", "as used in", "unless the context")
    body = [p for p in paras if len(p) > 120 and not p.lower().startswith(boilerplate)]
    if not body:
        return None
    out, size = [], 0
    for p in body:
        if size and size + len(p) > max_chars:
            break
        out.append(p)
        size += len(p)
    return "\n\n".join(out)


# ---------------------------------------------------------------- costs as presented
# Korean names for common cost lines (concept local name -> label). Lines not listed keep the
# company's own English label.
COST_NAMES = {
    "LaborAndRelatedExpense": "인건비", "SalariesAndWages": "인건비", "EmployeeBenefitsExpense": "인건비",
    "LaborAndRelatedExpenseAndOtherBenefits": "인건비", "SalariesWagesAndOfficersCompensation": "인건비",
    "OtherLaborRelatedExpenses": "성과급 등 기타 인건비",
    "FuelCosts": "연료비", "AircraftFuelAndRelatedTaxes": "연료비", "FuelAndPurchasedPowerCostOfSales": "연료·구매전력",
    "CostOfPurchasedPower": "구매 전력비", "UtilitiesOperatingExpenseFuelAndPurchasedPower": "연료·구매전력",
    "RawMaterialsAndConsumablesUsed": "원재료비",
    "DepreciationDepletionAndAmortization": "감가상각비", "DepreciationAndAmortization": "감가상각비",
    "DepreciationExpense": "감가상각비", "DepreciationAndAmortisationExpense": "감가상각비",
    "CostOfRevenue": "매출원가", "CostOfGoodsAndServicesSold": "매출원가", "CostOfGoodsSold": "매출원가",
    "CostOfSales": "매출원가", "CostOfServices": "서비스 원가",
    "ResearchAndDevelopmentExpense": "연구개발비", "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost": "연구개발비",
    "SellingGeneralAndAdministrativeExpense": "판매관리비", "SellingAndMarketingExpense": "판매·마케팅비",
    "GeneralAndAdministrativeExpense": "일반관리비", "AdministrativeExpense": "일반관리비",
    "SellingExpense": "판매비", "DistributionCosts": "물류·판매비",
    "ProfessionalAndContractServicesExpense": "외주 용역비", "LandingFeesAndOtherRentals": "공항 이용료·임차료",
    "AircraftMaintenanceMaterialsAndRepairs": "항공기 정비비", "AircraftRental": "항공기 임차료",
    "AirlineCapacityPurchaseArrangements": "지역 항공사 위탁비", "CostOfServicesCatering": "기내 서비스",
    "FeeAndCommissionExpense": "운항비·수수료", "OperatingLeasesRentExpenseNet": "임차료",
    "AmortizationOfIntangibleAssets": "무형자산 상각", "RestructuringCharges": "구조조정비",
    "OtherCostAndExpenseOperating": "기타", "OtherOperatingIncomeExpenseNet": "기타",
    "TaxesExcludingIncomeAndExciseTaxes": "세금(법인세 제외)", "InsuranceExpense": "보험료",
    "MarketingAndAdvertisingExpense": "광고비", "TechnologyServicesCosts": "기술 비용",
}
# Company-specific lines are named by label; common ones get a Korean name too.
LABEL_NAMES = {
    "fulfillment": "물류(풀필먼트)", "technology and infrastructure": "기술·인프라", "technology and content": "기술·콘텐츠",
    "sales and marketing": "판매·마케팅비", "ship operating expenses": "선박 운영비", "vessel operating expenses": "선박 운영비",
    "voyage expenses": "운항비", "purchased transportation": "외부 운송비", "fuel": "연료비",
    "compensation and benefits": "인건비", "salaries and benefits": "인건비", "operating and maintenance": "운영·유지보수비",
    "operation, maintenance and other": "운영·유지보수비", "property and other taxes": "재산세 등",
    "food and paper": "식재료·포장재", "payroll and employee benefits": "인건비", "occupancy and other operating expenses": "점포 운영비",
    "maintenance and repairs": "정비·수선비", "rentals": "임차료", "rent": "임차료", "marketing": "마케팅비",
}
_REVENUE_LOCAL = {c.split(":")[1] for c in REVENUE_CONCEPTS} | {
    "Revenues", "RevenueFromRenderingOfServices", "RegulatedAndUnregulatedOperatingRevenue",
    "RegulatedOperatingRevenue", "ElectricUtilityRevenue", "OperatingLeasesIncomeStatementLeaseRevenue"}
_OPINC_LOCAL = {"OperatingIncomeLoss", "ProfitLossFromOperatingActivities"}
_SUBTOTAL_LOCAL = {"GrossProfit", "CostsAndExpenses", "OperatingExpenses", "OperatingExpense",
                   "CostOfGoodsAndServicesSoldAndOperatingExpenses", "BenefitsLossesAndExpenses"}


def _local(concept: str) -> str:
    return str(concept).replace(":", "_").split("_", 1)[-1]


def presented_costs(income: pd.DataFrame) -> dict | None:
    """Operating cost lines exactly as the company presents them on the income statement
    (by nature for airlines, shipping, utilities and many IFRS filers; by function otherwise).

    ``income`` is edgartools ``Statement.to_dataframe()`` (concept, label, abstract, period
    columns). Lines between revenue and operating income are taken; subtotals are removed by
    choosing the set of lines that sums to total operating cost (revenue - operating income).
    Returns {"periods": [column...], "items": DataFrame(label x period), "revenue": Series,
    "operating_income": Series, "names": {label: original}} or None.
    """
    if income is None or income.empty or "concept" not in income:
        return None
    import re

    periods = [c for c in income.columns if re.match(r"^\d{4}-\d{2}-\d{2}", str(c))]
    periods = [c for c in periods if "(FY)" in str(c) or "(" not in str(c)][:3]
    if not periods:
        return None
    rows = income.reset_index(drop=True)
    locals_ = rows["concept"].map(_local)
    if "dimension" in rows:
        keep = ~rows["dimension"].fillna(False).astype(bool)
        rows, locals_ = rows[keep].reset_index(drop=True), locals_[keep].reset_index(drop=True)
    rev_idx = [i for i, c in enumerate(locals_) if c in _REVENUE_LOCAL]
    op_idx = [i for i, c in enumerate(locals_) if c in _OPINC_LOCAL]
    if not rev_idx or not op_idx:
        return None
    op_i = op_idx[0]
    rev_before = [i for i in rev_idx if i < op_i]
    if not rev_before:
        return None
    # the revenue total is the largest revenue line above operating income
    latest = periods[0]
    rev_i = max(rev_before, key=lambda i: pd.to_numeric(rows.loc[i, latest], errors="coerce") or 0)
    revenue = pd.to_numeric(rows.loc[rev_i, periods], errors="coerce")
    opinc = pd.to_numeric(rows.loc[op_i, periods], errors="coerce")
    block = rows.iloc[max(rev_before) + 1:op_i]
    block = block[~block.get("abstract", False).fillna(False).astype(bool)]
    block = block[~block["concept"].map(_local).isin(_SUBTOTAL_LOCAL | _REVENUE_LOCAL)]
    block = block[~block["label"].astype(str).str.lower().str.startswith("total")]
    if block.empty:
        return None
    values = block.set_index(block.index)[periods].apply(pd.to_numeric, errors="coerce").abs()
    total_cost = float(revenue[latest] - opinc[latest])
    lines = values[latest].dropna()
    members, exact = pick_members(lines, total_cost)
    if not members:
        return None
    chosen = block.loc[members]
    names, labels = {}, []
    for _, r in chosen.iterrows():
        orig = str(r["label"]).strip()
        key = orig.lower().replace("&", "and").rstrip(":").strip()
        key = " ".join(key.split())
        kr = COST_NAMES.get(_local(r["concept"])) or LABEL_NAMES.get(key)
        name = kr or orig
        labels.append(name)
        names[name] = orig
    labels = _unique(labels)
    items = values.loc[members]
    items.index = labels
    items = items.sort_values(latest, ascending=False)
    return {"periods": periods, "items": items, "revenue": revenue, "operating_income": opinc,
            "names": dict(zip(labels, [names.get(l.split(" (")[0], l) for l in labels])), "exact": exact}
