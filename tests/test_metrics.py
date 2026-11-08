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


def test_dividend_history_streaks_and_partial_year():
    from edger.metrics import dividend_history
    idx = pd.to_datetime(["2021-03-01", "2021-09-01", "2022-03-01", "2022-09-01",
                          "2023-03-01", "2023-09-01", "2024-03-01", "2024-09-01", "2025-03-01"])
    pay = pd.Series([1, 1, 1.1, 1.1, 1.1, 1.1, 1.2, 1.2, 1.3], index=idx, dtype=float)
    prices = pd.Series([50.0, 55.0, 60.0, 65.0, 70.0],
                       index=pd.to_datetime(["2021-12-31", "2022-12-30", "2023-12-29", "2024-12-31", "2025-06-30"]))
    h = dividend_history(pay, prices, today=pd.Timestamp("2025-07-01"))
    a = h["annual"]
    assert a.loc[2025, "partial"] and not a.loc[2024, "partial"]
    assert a.loc[2022, "dps"] == pytest.approx(2.2) and a.loc[2024, "growth"] == pytest.approx(2.4 / 2.2 - 1)
    assert a.loc[2023, "yield"] == pytest.approx(2.2 / 60)
    assert h["paid_streak"] == 4          # 2021-2024 complete years
    assert h["raise_streak"] == 1         # 2023 was flat, 2024 raised
    assert h["per_year"] == 2
    assert h["ttm_dps"] == pytest.approx(1.2 + 1.3)  # payments after 2024-07-01


def test_dividend_history_stopped_payer():
    from edger.metrics import dividend_history
    pay = pd.Series([1.0, 1.0], index=pd.to_datetime(["2018-03-01", "2019-03-01"]))
    h = dividend_history(pay, None, today=pd.Timestamp("2025-07-01"))
    assert h["paid_streak"] == 0 and h["raise_streak"] == 0


# --- debt tag patterns, each taken from a real 10-K/20-F balance sheet (values in $B)
def _bs(**tags):
    rows = [dict(concept="us-gaap:Revenues", unit="USD", period_type="duration", period_start="2025-01-01",
                 period_end="2025-12-31", numeric_value=100.0, filing_date="2026-02-01", form_type="10-K")]
    for concept, value in tags.items():
        prefix = "ifrs-full" if concept.startswith("ifrs_") else "us-gaap"
        rows.append(dict(concept=f"{prefix}:{concept.removeprefix('ifrs_')}", unit="USD", period_type="instant",
                         period_start=None, period_end="2025-12-31", numeric_value=value,
                         filing_date="2026-02-01", form_type="10-K"))
    table, _ = build_table(pd.DataFrame(rows), "annual")
    return table.iloc[-1]


@pytest.mark.parametrize("name,tags,expected", [
    ("AAPL: LongTermDebt incl. current + CP", dict(LongTermDebt=78.114, LongTermDebtNoncurrent=68.208,
                                                     LongTermDebtCurrent=9.906, CommercialPaper=1.997), 80.111),
    ("MCD: LongTermDebt excludes current", dict(LongTermDebt=39.973, LongTermDebtNoncurrent=39.973,
                                                 LongTermDebtCurrent=0.725, CommercialPaper=0.798), 41.496),
    ("KO: debt-and-lease tags + CP + other", dict(LongTermDebtAndCapitalLeaseObligations=42.119,
                                                  LongTermDebtAndCapitalLeaseObligationsCurrent=1.822,
                                                  CommercialPaper=1.495, OtherShortTermBorrowings=0.056), 45.492),
    ("NVDA: noncurrent + DebtCurrent only", dict(LongTermDebtNoncurrent=7.469, DebtCurrent=0.999), 8.468),
    ("O: REIT notes + loans + secured + CP", dict(NotesPayable=25.032, LoansPayable=1.702, SecuredDebt=0.038,
                                                  CommercialPaper=0.517), 27.289),
    ("JPM: debt incl. leases + short-term", dict(LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities=435.206,
                                                 ShortTermBorrowings=64.776), 499.982),
    ("TSM: IFRS bonds + bank borrowings", dict(ifrs_NoncurrentPortionOfNoncurrentBondsIssued=926.6,
                                               ifrs_CurrentBondsIssuedAndCurrentPortionOfNoncurrentBondsIssued=57.1,
                                               ifrs_LongtermBorrowings=31.8), 1015.5),
])
def test_debt_patterns(name, tags, expected):
    row = _bs(**tags)
    assert row["debt"] == pytest.approx(expected, abs=1e-3), name


def test_negative_equity_ratios_are_not_numbers():
    row = _bs(LongTermDebt=40.0, Liabilities=60.0, StockholdersEquity=-1.8, Assets=58.2)
    assert pd.isna(row["debt_ratio"]) and pd.isna(row["de_ratio"])


def test_lease_inclusive_de():
    row = _bs(LongTermDebt=80.0, OperatingLeaseLiability=12.0, FinanceLeaseLiability=2.0, StockholdersEquity=100.0)
    assert row["de_ratio"] == pytest.approx(0.8) and row["de_ratio_lease"] == pytest.approx(0.94)


def test_foreign_filer_valuation_uses_fx(monkeypatch):
    """TSM-style: financials in TWD, ADR priced in USD. Multiples must use converted values
    and per-share figures that mix ADRs with ordinary shares must be left out."""
    from edger import ui
    annual = pd.DataFrame({"label": ["FY24"], "net_income": [1000.0], "revenue": [3000.0], "eps": [40.0],
                           "equity": [4000.0], "debt": [1000.0], "cash": [2000.0]},
                          index=pd.to_datetime(["2024-12-31"]))
    for col in ui.TTM_FLOWS:
        if col not in annual:
            annual[col] = float("nan")
    monkeypatch.setattr(ui, "load_table", lambda t, p, n: (annual if p == "annual" else pd.DataFrame(), "TWD"))
    monkeypatch.setattr(ui, "load_quote", lambda t: {"price": 300.0, "market_cap": 900.0, "currency": "USD",
                                                     "change": None, "source": "Yahoo Finance"})
    monkeypatch.setattr(ui, "load_fx", lambda a, b: 0.03)  # 1 TWD = 0.03 USD
    snap = ui.load_snapshot("TSM")
    v = snap["valuation"]
    assert v["per"] == pytest.approx(900 / (1000 * 0.03))   # 30x, not 0.9x
    assert v["pbr"] == pytest.approx(900 / (4000 * 0.03))
    assert v["bps"] is None and v["shares"] is None
    assert snap["fx"]["rate"] == 0.03 and snap["stale_since"] is not None



def _pay(rows):
    return pd.Series([v for _, v in rows], index=pd.to_datetime([d for d, _ in rows]), dtype=float)


def test_raise_streak_ignores_payment_count_shifts():
    """KO-like: one year gets 5 payments, the next 3; both are still raises."""
    from edger.metrics import dividend_history
    pay = _pay([("2021-03-01", 1.0), ("2021-06-01", 1.0), ("2021-09-01", 1.0), ("2021-12-01", 1.0),
                ("2022-03-01", 1.1), ("2022-06-01", 1.1), ("2022-09-01", 1.1), ("2022-11-28", 1.1), ("2022-12-30", 1.1),
                ("2023-06-01", 1.2), ("2023-09-01", 1.2), ("2023-12-01", 1.2)])
    assert dividend_history(pay, None, today=pd.Timestamp("2024-07-01"))["raise_streak"] == 2


def test_raise_streak_counts_raise_in_last_payment():
    """MSFT 2009-like: the raise lands in the year's last payment only."""
    from edger.metrics import dividend_history
    pay = _pay([(f"2021-{m:02d}-01", 0.11) for m in (3, 6, 9)] + [("2021-12-01", 0.13)]
               + [(f"2022-{m:02d}-01", 0.13) for m in (3, 6, 9, 12)])
    assert dividend_history(pay, None, today=pd.Timestamp("2023-07-01"))["raise_streak"] == 1


def test_raise_streak_ignores_stray_payment():
    """KO 2001-like: a doubled data-error payment must not make the next year look like a cut."""
    from edger.metrics import dividend_history
    pay = _pay([("2021-03-01", 0.09), ("2021-06-01", 0.09), ("2021-09-01", 0.18), ("2021-09-05", 0.09),
                ("2021-12-01", 0.09), *[(f"2022-{m:02d}-01", 0.10) for m in (3, 6, 9, 12)]])
    assert dividend_history(pay, None, today=pd.Timestamp("2023-07-01"))["raise_streak"] == 1


def test_raise_streak_resets_on_cut():
    from edger.metrics import dividend_history
    pay = _pay([*[(f"2021-{m:02d}-01", 0.52) for m in (3, 6, 9, 12)],
                *[(f"2022-{m:02d}-01", 0.2775) for m in (3, 6, 9, 12)]])
    assert dividend_history(pay, None, today=pd.Timestamp("2023-07-01"))["raise_streak"] == 0


def _flow(concept, start, end, value, filed, form="10-Q"):
    return dict(concept=f"us-gaap:{concept}", unit="USD", period_type="duration", period_start=start,
                period_end=end, numeric_value=value, filing_date=filed, form_type=form)


def test_q4_uses_originally_reported_values():
    """FRO 2013: FY revenue restated years later ($517M -> $134M). Q4 must come from the
    original FY minus the original 9-month YTD, not restated FY minus original YTD (-$240M)."""
    rows = [
        _flow("Revenues", "2013-01-01", "2013-03-31", 126.0, "2013-05-30"),
        _flow("Revenues", "2013-04-01", "2013-06-30", 121.0, "2013-08-29"),
        _flow("Revenues", "2013-01-01", "2013-06-30", 247.0, "2013-08-29"),
        _flow("Revenues", "2013-07-01", "2013-09-30", 126.0, "2013-12-13"),
        _flow("Revenues", "2013-01-01", "2013-09-30", 373.0, "2013-12-13"),
        _flow("Revenues", "2013-01-01", "2013-12-31", 517.0, "2014-03-21", "20-F"),
        _flow("Revenues", "2013-01-01", "2013-12-31", 134.0, "2016-03-21", "20-F"),  # restated
    ]
    q, _ = build_table(pd.DataFrame(rows), "quarterly")
    assert q.loc["2013-12-31", "revenue"] == pytest.approx(144.0)
    assert (q["revenue"] >= 0).all()


def test_stale_quarterly_history_is_hidden():
    """Quarterly data that stopped years before the latest annual report (moved to half-year
    reports) must not be shown as the current quarter."""
    rows = [_flow("Revenues", f"2013-{m:02d}-01", f"2013-{m + 2:02d}-{30 if m + 2 in (6, 9) else 31}", 100.0, "2014-01-01")
            for m in (1, 4, 7)]
    rows += [_flow("Revenues", f"{y}-01-01", f"{y}-12-31", 500.0, f"{y + 1}-03-01", "20-F") for y in range(2013, 2026)]
    df = pd.DataFrame(rows)
    assert build_table(df, "quarterly")[0].empty
    assert build_table(df, "ttm")[0].empty
    assert not build_table(df, "annual")[0].empty


@pytest.mark.parametrize("latest,prev,word", [
    (-65.5, 0.127, "적자전환"), (10.0, -5.0, "흑자전환"), (-8.0, -5.0, "적자지속"), (-3.0, -5.0, "적자축소"),
    (10.0, 5.0, None),
])
def test_turnaround(latest, prev, word):
    from edger.metrics import turnaround
    assert turnaround(latest, prev) == word


def _fake_yfinance(monkeypatch, financial_currency, trading_currency):
    """yfinance stand-in with Yahoo's row names and sign conventions (outflows negative)."""
    import sys, types
    ends = pd.to_datetime(["2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30", "2026-09-30"])
    def frame(rows):
        return pd.DataFrame(rows, index=ends).T[ends[::-1]]  # Yahoo: newest column first
    income = frame({"Total Revenue": [100, 110, 120, 130, 150], "Operating Income": [40, 44, 48, 52, 60],
                    "Net Income": [30, 33, 36, 39, 45], "Diluted Average Shares": [10, 10, 10, 10, 10]})
    cash = frame({"Operating Cash Flow": [50, 55, 60, 65, 70], "Capital Expenditure": [-20, -20, -20, -20, -20],
                  "Cash Dividends Paid": [-5, -5, -5, -5, -6]})
    bal = frame({"Total Assets": [500] * 5, "Stockholders Equity": [300] * 5, "Cash And Cash Equivalents": [80] * 5,
                 "Long Term Debt": [60] * 5, "Current Debt": [10] * 5,
                 "Total Liabilities Net Minority Interest": [200] * 5})
    class T:
        def __init__(self, t):
            self.quarterly_income_stmt, self.quarterly_cashflow, self.quarterly_balance_sheet = income, cash, bal
            self.info = {"financialCurrency": financial_currency, "currency": trading_currency}
    fake = types.ModuleType("yfinance"); fake.Ticker = T
    monkeypatch.setitem(sys.modules, "yfinance", fake)


def test_yahoo_quarterly_mapping(monkeypatch):
    from edger import market
    _fake_yfinance(monkeypatch, "USD", "USD")
    y = market.yahoo_quarterly("FRO")
    raw = y["raw"]
    assert list(raw.index.strftime("%Y-%m")) == ["2025-09", "2025-12", "2026-03", "2026-06", "2026-09"]  # oldest first
    assert raw["capex"].iloc[-1] == 20 and raw["dividends"].iloc[-1] == 6    # outflows made positive
    assert raw["eps"].iloc[-1] == pytest.approx(4.5) and y["per_share_ok"]


def test_yahoo_adr_drops_per_share(monkeypatch):
    """TSM-like: reports in TWD, ADR trades in USD; Yahoo share counts are per ADR."""
    from edger import market
    _fake_yfinance(monkeypatch, "TWD", "USD")
    y = market.yahoo_quarterly("TSM")
    assert y["currency"] == "TWD" and not y["per_share_ok"]
    assert y["raw"]["eps"].isna().all()


def test_period_table_falls_back_to_yahoo(monkeypatch):
    from edger import data
    _fake_yfinance(monkeypatch, "USD", "USD")
    monkeypatch.setattr(data, "fetch_facts", lambda t: pd.DataFrame())  # no SEC quarterly data
    q, cur = data.period_table("FRO", "quarterly", 12)
    assert q.attrs["source"] == "Yahoo" and q.attrs["quarters"] == 5 and cur == "USD"
    assert q["debt"].iloc[-1] == 70                       # long-term + current debt
    t, _ = data.period_table("FRO", "ttm", 12)
    assert t["revenue"].iloc[-1] == 110 + 120 + 130 + 150  # last four quarters
    assert t["fcf"].iloc[-1] == (55 + 60 + 65 + 70) - 80


def test_pick_members_prefers_detail_over_parents():
    """AAPL-like: 'Products' sits next to its parts; the detailed set should win."""
    from edger.business import pick_members
    v = pd.Series({"Products": 355.5, "iPhone": 254.1, "Mac": 37.9, "iPad": 27.9, "Wearables": 35.6,
                   "Services": 123.3})
    members, exact = pick_members(v, 478.8)
    assert exact and set(members) == {"iPhone", "Mac", "iPad", "Wearables", "Services"}


def test_pick_members_partial_cover():
    from edger.business import pick_members
    members, exact = pick_members(pd.Series({"A": 50.0, "B": 30.0}), 100.0)
    assert not exact and members == ["A", "B"]


def _xbrl_fact(concept, value, end="2025-12-31", start="2025-01-01", **dims):
    row = {"concept": concept, "numeric_value": value, "period_type": "duration", "period_start": start,
           "period_end": end, "is_dimensioned": bool(dims), "dimension_member_label": None,
           "dim_us-gaap_StatementBusinessSegmentsAxis": None, "dim_srt_ConsolidationItemsAxis": None,
           "dim_srt_StatementGeographicalAxis": None}
    for k, v in dims.items():
        row[f"dim_{k}"] = v
    return row


def test_breakdowns_segments_with_operating_segments_marker():
    """Segment facts tagged together with ConsolidationItemsAxis=OperatingSegmentsMember (AAPL)
    count as single-axis; labels come from the member names, not 'Operating segments'."""
    from edger.business import breakdowns
    seg, cons = "us-gaap_StatementBusinessSegmentsAxis", "srt_ConsolidationItemsAxis"
    rows = [_xbrl_fact("us-gaap:Revenues", 100.0)]
    for member, value, opi in (("x:AmericasSegmentMember", 60.0, 20.0), ("x:EuropeSegmentMember", 40.0, 10.0)):
        for concept, v in (("us-gaap:Revenues", value), ("us-gaap:OperatingIncomeLoss", opi)):
            r = _xbrl_fact(concept, v, **{seg: member, cons: "us-gaap:OperatingSegmentsMember"})
            r["dimension_member_label"] = "Operating segments"
            rows.append(r)
    b = breakdowns(pd.DataFrame(rows))
    part = b["segment"]
    assert list(part["values"].index) == ["Americas", "Europe"]
    assert part["share"].tolist() == [0.6, 0.4] and part["exact"]
    assert part["op_income"].loc["Americas"].iloc[-1] == 20.0


def test_breakdowns_remainder_is_labelled():
    from edger.business import breakdowns
    geo = "srt_StatementGeographicalAxis"
    rows = [_xbrl_fact("us-gaap:Revenues", 100.0),
            _xbrl_fact("us-gaap:Revenues", 50.0, **{geo: "country:US"}),
            _xbrl_fact("us-gaap:Revenues", 30.0, **{geo: "country:CN"})]
    part = breakdowns(pd.DataFrame(rows))["geo"]
    assert "기타(미분류)" in part["values"].index and not part["exact"]
    assert part["share"].sum() == pytest.approx(1.0)


def test_overview_reflows_wrapped_text():
    from edger.business import overview
    text = ("ITEM 4. INFORMATION ON THE COMPANY\n\nOur History and Structure\n\n"
            "Our legal name is Example Co. We were founded in 1987 as a joint venture among the government and\n\n"
            "other private investors and were incorporated in the country as a company limited by shares.\n")
    out = overview(text)
    assert out.startswith("Our legal name is Example Co.") and "government and other private" in out


def test_annual_ignores_ttm_figures_in_10q():
    """AMZN reports trailing-twelve-month results in its 10-Qs; they are not fiscal years."""
    rows = [_flow("Revenues", "2024-01-01", "2024-12-31", 638.0, "2025-02-07", "10-K"),
            _flow("Revenues", "2024-04-01", "2025-03-31", 650.0, "2025-05-02", "10-Q"),
            _flow("Revenues", "2024-07-01", "2025-06-30", 670.0, "2025-08-01", "10-Q"),
            _flow("Revenues", "2025-01-01", "2025-12-31", 717.0, "2026-02-06", "10-K")]
    a, _ = build_table(pd.DataFrame(rows), "annual")
    assert list(a.index.strftime("%Y-%m-%d")) == ["2024-12-31", "2025-12-31"]


def test_annual_keeps_year_whose_latest_copy_is_another_form():
    """The latest copy of a fiscal year can be an 8-K recast or the proxy (DEF 14A pay-versus-
    performance table); the annual-report value must still be used, not the year dropped."""
    rows = [_flow("Revenues", "2025-01-01", "2025-12-31", 100.0, "2026-02-06", "10-K"),
            _flow("NetIncomeLoss", "2025-01-01", "2025-12-31", 20.0, "2026-02-06", "10-K"),
            _flow("NetIncomeLoss", "2025-01-01", "2025-12-31", 20.0, "2026-04-09", "DEF 14A")]
    a, _ = build_table(pd.DataFrame(rows), "annual")
    assert a["net_income"].iloc[-1] == 20.0


def test_cost_structure_adds_up_to_revenue():
    from edger.metrics import cost_structure
    aapl = pd.Series({"revenue": 478.8, "operating_income": 158.1, "cost_of_revenue": 245.2, "rnd": 45.8,
                      "sga": 29.8})
    cs = cost_structure(aapl)
    assert cs["parts"].sum() == pytest.approx(478.9, abs=0.2) and "기타 영업비용" not in cs["parts"]
    msft = pd.Series({"revenue": 331.8, "operating_income": 155.2, "cost_of_revenue": 106.4, "rnd": 35.6,
                      "selling": 26.7, "gna": 8.0})          # no SG&A total: selling + G&A
    assert cost_structure(msft)["parts"]["판매관리비"] == pytest.approx(34.7)
    amzn = pd.Series({"revenue": 716.9, "operating_income": 80.0, "cost_of_revenue": 356.4, "gna": 11.2})
    cs = cost_structure(amzn)                                 # fulfillment etc. untagged
    assert cs["parts"]["기타 영업비용"] == pytest.approx(716.9 - 80.0 - 356.4 - 11.2)
    loss = cost_structure(pd.Series({"revenue": 100.0, "operating_income": -10.0, "cost_of_revenue": 80.0}))
    assert loss["loss"] and "영업이익" not in loss["parts"] and loss["base"] == pytest.approx(110.0)


def test_presented_costs_by_nature():
    """DAL-like income statement: costs by nature between revenue and operating income, with
    an abstract header and a 'Total operating expense' row that must not double count."""
    from edger.business import presented_costs
    col, prev = "2025-12-31 (FY)", "2024-12-31 (FY)"
    rows = [
        ("us-gaap_RevenuesAbstract", "Operating Revenue:", True, None, None),
        ("us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax", "Total operating revenue", False, 63.4, 61.6),
        ("us-gaap_CostsAndExpensesAbstract", "Operating Expense:", True, None, None),
        ("us-gaap_LaborAndRelatedExpense", "Salaries and related costs", False, 17.5, 16.2),
        ("us-gaap_FuelCosts", "Aircraft fuel and related taxes", False, 9.8, 10.9),
        ("dal_AncillaryBusinessesAndRefineryExpenses", "Ancillary businesses and refinery", False, 6.0, 5.8),
        ("us-gaap_OtherCostAndExpenseOperating", "Other", False, 24.3, 22.7),
        ("us-gaap_CostsAndExpenses", "Total operating expense", False, 57.6, 55.6),
        ("us-gaap_OperatingIncomeLoss", "Operating Income", False, 5.8, 6.0),
        ("us-gaap_InterestIncomeExpenseNonoperatingNet", "Interest expense, net", False, -0.7, -0.8),
    ]
    df = pd.DataFrame([{"concept": c, "label": l, "abstract": a, col: v, prev: p} for c, l, a, v, p in rows])
    out = presented_costs(df)
    assert out["exact"]
    assert list(out["items"].index) == ["기타", "인건비", "연료비", "Ancillary businesses and refinery"]
    assert out["items"][col].sum() == pytest.approx(57.6)
    assert out["names"]["인건비"] == "Salaries and related costs"
    assert out["operating_income"][col] == 5.8 and out["revenue"][prev] == 61.6


def test_split_adjusted_shares_and_per():
    """AAPL-like 4-for-1 split on 2020-08-31: share counts filed before it are x4, so PER
    (market cap / TTM net income) is continuous across the split."""
    from edger.metrics import per_history, split_adjusted_shares
    facts = pd.DataFrame([
        dict(concept="dei:EntityCommonStockSharesOutstanding", numeric_value=4.3e9, period_end="2020-01-17",
             filing_date="2020-01-29"),
        dict(concept="dei:EntityCommonStockSharesOutstanding", numeric_value=17.0e9, period_end="2020-10-16",
             filing_date="2020-10-30"),
    ])
    splits = pd.Series([4.0], index=pd.to_datetime(["2020-08-31"]))
    sh = split_adjusted_shares(facts, splits)
    assert sh.loc["2020-01-17"] == pytest.approx(17.2e9) and sh.loc["2020-10-16"] == pytest.approx(17.0e9)

    prices = pd.Series(100.0, index=pd.bdate_range("2020-01-01", "2020-12-31"))  # split-adjusted
    ttm = pd.DataFrame({"net_income": [57e9, 57e9, 57e9, 57e9]},
                       index=pd.to_datetime(["2019-12-28", "2020-03-28", "2020-06-27", "2020-09-26"]))
    h = per_history(prices, ttm, sh)
    # before the split: 100 * 17.2e9 / 57e9 ~= 30.2, after: 100 * 17.0e9 / 57e9 ~= 29.8 — no 4x jump
    assert h["per"].min() > 25 and h["per"].max() < 35


def test_per_history_blanks_losses():
    from edger.metrics import per_history
    prices = pd.Series(50.0, index=pd.bdate_range("2024-01-01", "2024-06-30"))
    ttm = pd.DataFrame({"net_income": [-1e9, 2e9]}, index=pd.to_datetime(["2023-12-31", "2024-03-31"]))
    h = per_history(prices, ttm, pd.Series([1e9], index=pd.to_datetime(["2023-12-31"])))
    assert h.loc[:"2024-03-29", "per"].isna().all() and h.loc["2024-04-05":, "per"].notna().all()


def test_band_multiples():
    from edger.metrics import band_multiples
    per = pd.Series(range(10, 41), dtype=float)  # PER 10..40
    assert band_multiples(per) == [13, 19, 25, 30, 35]
    assert band_multiples(pd.Series([20.0] * 5)) == []  # not enough history


def test_tradingview_symbol():
    from edger.ui import tradingview_symbol
    assert tradingview_symbol("aapl", ["Nasdaq"]) == "NASDAQ:AAPL"
    assert tradingview_symbol("BRK.B", ["NYSE"]) == "NYSE:BRK.B"
    assert tradingview_symbol("SPY", ["NYSE Arca"]) == "AMEX:SPY"
    assert tradingview_symbol("XYZ", []) == "XYZ"  # TradingView resolves bare tickers
