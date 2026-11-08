import pandas as pd
import pytest

from edger import data, fmt
from edger.metrics import build_table, change


@pytest.fixture(scope="module")
def facts():
    return data.fetch_facts("DEMO")


def test_annual_table(facts):
    table, currency = build_table(facts, "annual", 8)
    assert currency == "USD"
    assert len(table) == 8
    assert table["label"].iloc[-1] == "FY25"
    assert table["revenue"].notna().all()
    # FCF = OCF - capex
    row = table.iloc[-1]
    assert row["fcf"] == pytest.approx(row["ocf"] - row["capex"])
    assert 0 < row["operating_margin"] < 1


def test_quarterly_derives_q4_and_ytd_cash_flow(facts):
    q, _ = build_table(facts, "quarterly", 8)
    annual, _ = build_table(facts, "annual", 10)
    fy25 = q[q.index.year == 2025]
    assert len(fy25) == 4  # Q4 has no standalone fact; it is derived from FY - 9M
    assert fy25["revenue"].sum() == pytest.approx(annual.loc["2025-12-31", "revenue"], rel=1e-9)
    # cash flow is reported YTD only in the demo, so every quarter is derived
    assert fy25["ocf"].notna().all()
    assert fy25["ocf"].sum() == pytest.approx(annual.loc["2025-12-31", "ocf"], rel=1e-9)


def test_restated_values_use_latest_filing():
    rows = [
        dict(concept="us-gaap:Revenues", unit="USD", period_type="duration", period_start="2022-01-01",
             period_end="2022-12-31", numeric_value=100.0, filing_date="2023-02-01", form_type="10-K"),
        dict(concept="us-gaap:Revenues", unit="USD", period_type="duration", period_start="2022-01-01",
             period_end="2022-12-31", numeric_value=110.0, filing_date="2024-02-01", form_type="10-K"),
    ]
    table, _ = build_table(pd.DataFrame(rows), "annual")
    assert table["revenue"].tolist() == [110.0]


def test_concept_fallback_merges_tag_switch():
    def row(concept, year, value):
        return dict(concept=concept, unit="USD", period_type="duration", period_start=f"{year}-01-01",
                    period_end=f"{year}-12-31", numeric_value=value, filing_date=f"{year + 1}-02-01",
                    form_type="10-K")
    rows = [row("us-gaap:SalesRevenueNet", 2017, 50.0),
            row("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 2018, 60.0)]
    table, _ = build_table(pd.DataFrame(rows), "annual")
    assert table["revenue"].tolist() == [50.0, 60.0]
    latest, delta = change(table, "revenue")
    assert latest == 60.0 and delta == pytest.approx(0.2)


def test_empty_facts():
    table, currency = build_table(pd.DataFrame(), "annual")
    assert table.empty and currency == "USD"


@pytest.mark.parametrize("value,expected", [
    (391_035_000_000, "$391.0B"), (-2.5e6, "-$2.5M"), (None, "–"), (float("nan"), "–"),
])
def test_money(value, expected):
    assert fmt.money(value) == expected
