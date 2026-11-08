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
