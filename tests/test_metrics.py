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


def test_ttm_sums_last_four_quarters(facts):
    from edger.metrics import ttm
    q, _ = build_table(facts, "quarterly", 12)
    annual, _ = build_table(facts, "annual", 10)
    t = ttm(q)
    assert t["revenue"] == pytest.approx(annual["revenue"].iloc[-1], rel=1e-9)  # Q1..Q4 2025 = FY25


def test_ttm_rejects_gaps(facts):
    from edger.metrics import ttm
    q, _ = build_table(facts, "quarterly", 12)
    assert ttm(q.drop(q.index[-2])) is None


def test_cagr():
    from edger.metrics import cagr
    t = pd.DataFrame({"revenue": [100.0, 110.0, 121.0, 133.1]})
    assert cagr(t, "revenue", 3) == pytest.approx(0.10)
    assert cagr(t, "revenue", 5) is None
    assert cagr(pd.DataFrame({"x": [-1.0, 2.0]}), "x", 1) is None


def test_valuation_multiples():
    from edger.metrics import valuation
    v = valuation(1000.0, {"net_income": 50.0, "revenue": 500.0, "fcf": 40.0, "operating_income": 80.0},
                  pd.Series({"equity": 250.0, "debt": 100.0, "cash": 60.0}))
    assert v["per"] == 20 and v["psr"] == 2 and v["pbr"] == 4
    assert v["ev"] == 1040 and v["ev_ebit"] == 13 and v["fcf_yield"] == pytest.approx(0.04)
    assert valuation(1000.0, {"net_income": -5.0}, None)["per"] is None  # loss-making: no PER


def test_deep_metrics_present(facts):
    table, _ = build_table(facts, "annual", 8)
    assert table["roe"].notna().all() and table["roic"].notna().all()
    assert (table["net_debt"] == table["debt"] - table["cash"]).all()
    assert table["ebitda"].notna().all() and table["current_ratio"].notna().all()


def test_net_debt_unknown_without_debt_tags():
    def row(concept, kind, value):
        return dict(concept=concept, unit="USD", period_type=kind,
                    period_start="2022-01-01" if kind == "duration" else None, period_end="2022-12-31",
                    numeric_value=value, filing_date="2023-02-01", form_type="10-K")
    table, _ = build_table(pd.DataFrame([row("us-gaap:Revenues", "duration", 100.0),
                                         row("us-gaap:CashAndCashEquivalentsAtCarryingValue", "instant", 30.0)]))
    assert table["net_debt"].isna().all()  # not "-cash"
    assert table["ebitda"].isna().all()  # no D&A tag: no EBITDA rather than EBIT


def test_normalize_xbrl_statement_shape():
    """Shape of edgartools Statement.to_dataframe(): concept/label/period columns/level/abstract/unit."""
    raw = pd.DataFrame({
        "concept": ["us-gaap_IncomeStatementAbstract", "us-gaap_Revenues", "us-gaap_NetIncomeLoss",
                    "us-gaap_EarningsPerShareDiluted", "us-gaap_Revenues"],
        "label": ["Income Statement", "Total net sales", "Net income", "Diluted EPS", "Products"],
        "2025-09-27 (FY)": [None, 416e9, 112e9, 7.46, 300e9],
        "2024-09-28 (FY)": [None, 391e9, 94e9, 6.08, 290e9],
        "2023-09-30 (FY)": [None, 383e9, 97e9, 6.13, 280e9],
        "2022-09-24 (FY)": [None, 394e9, 100e9, 6.11, 270e9],
        "level": [0, 1, 1, 1, 2],
        "abstract": [True, False, False, False, False],
        "dimension": [False, False, False, False, True],
        "unit": [None, "usd", "usd", "usdPerShare", "usd"],
        "balance": [None, "credit", "credit", None, "credit"],
    })
    from edger.data import normalize_xbrl_statement
    out = normalize_xbrl_statement(raw)
    assert list(out.columns) == ["label", "depth", "is_abstract", "kind", "25.09", "24.09", "23.09"]
    assert out["label"].tolist() == ["Income Statement", "Total net sales", "Net income", "Diluted EPS"]
    assert out["kind"].tolist() == ["money", "money", "money", "per_share"]
    assert out.loc[1, "25.09"] == 416e9


def test_normalize_prefers_quarter_over_ytd():
    from edger.data import normalize_xbrl_statement
    raw = pd.DataFrame({"label": ["Revenue"], "2025-06-28 (YTD)": [300.0], "2025-06-28 (Q3)": [100.0],
                        "2024-06-29 (Q3)": [90.0], "level": [0], "abstract": [False], "unit": ["usd"]})
    out = normalize_xbrl_statement(raw)
    assert [c for c in out.columns if "." in c] == ["25.06 Q3", "24.06 Q3"]
    # cash-flow statements in a 10-Q are year-to-date only: keep those
    ytd = normalize_xbrl_statement(raw.drop(columns=["2025-06-28 (Q3)", "2024-06-29 (Q3)"]))
    assert [c for c in ytd.columns if "." in c] == ["25.06 누적"]


def test_parse_stooq_csv():
    from edger.market import parse_stooq_csv, stooq_symbol
    s = parse_stooq_csv("Date,Open,High,Low,Close,Volume\n2026-11-05,1,2,0.5,10.5,100\n2026-11-06,1,2,0.5,11,100\n")
    assert s.tolist() == [10.5, 11.0] and str(s.index[-1].date()) == "2026-11-06"
    assert parse_stooq_csv("No data").empty
    assert parse_stooq_csv("Exceeded the daily hits limit").empty
    assert stooq_symbol("BRK.B") == "brk-b.us"


def test_quote_falls_back_when_yahoo_fails(monkeypatch):
    from edger import market
    import sys, types
    fake = types.ModuleType("yfinance")
    class Boom:
        def __init__(self, *a): raise RuntimeError("Too Many Requests")
    fake.Ticker = Boom
    monkeypatch.setitem(sys.modules, "yfinance", fake)
    hist = pd.Series([100.0, 110.0], index=pd.to_datetime(["2026-11-05", "2026-11-06"]), name="close")
    monkeypatch.setattr(market, "_stooq_history", lambda t: hist)
    q = market.quote("AAPL")
    assert q["price"] == 110.0 and q["source"] == "Stooq" and q["change"] == pytest.approx(0.1)
    assert q["market_cap"] is None  # left to the caller (SEC share count)


def test_market_cap_fallback_chain(monkeypatch):
    from edger import ui
    annual = pd.DataFrame({"shares_diluted": [9.0, 10.0]})
    monkeypatch.setattr(ui, "load_facts", lambda t: pd.DataFrame(columns=["concept", "numeric_value"]))
    cap, src = ui.market_cap_estimate("X", {"price": 5.0, "market_cap": None}, pd.DataFrame(), annual)
    assert cap == 50.0 and "희석" in src
    cap, src = ui.market_cap_estimate("X", {"price": 5.0, "market_cap": 99.0}, pd.DataFrame(), annual)
    assert cap == 99.0
    assert ui.market_cap_estimate("X", {"price": None}, pd.DataFrame(), annual) == (None, None)


def test_ttm_table_matches_fiscal_year(facts):
    t, _ = build_table(facts, "ttm", 12)
    a, _ = build_table(facts, "annual", 10)
    for end in ("2024-12-31", "2025-12-31"):
        for col in ("revenue", "operating_income", "net_income", "fcf", "roe"):
            assert t.loc[end, col] == pytest.approx(a.loc[end, col], rel=1e-9), (end, col)


def test_ttm_drops_windows_with_missing_quarter(facts):
    from edger.metrics import _ttm_table, _raw_table, prepare_facts, detect_currency
    f = prepare_facts(facts)
    q = _raw_table(f, "quarterly", detect_currency(f))
    q = q.drop(pd.Timestamp("2025-06-30"))
    t = _ttm_table(q)
    # windows ending 25.09 and 25.12 would span the gap: dropped, not summed over 3 quarters
    assert pd.Timestamp("2025-09-30") not in t.index
    assert pd.Timestamp("2025-12-31") not in t.index
    assert pd.Timestamp("2025-03-31") in t.index  # window before the gap is still fine
