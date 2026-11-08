"""Stock prices. SEC has no market data, so prices come from Yahoo Finance (yfinance), with
Stooq's free daily CSV as a fallback: Yahoo often rate-limits shared cloud hosts such as
Streamlit Community Cloud.

Every function degrades to empty results instead of raising, and records which source
answered, so the dashboard keeps working on SEC data alone.
"""
from __future__ import annotations

import io
import urllib.request

import numpy as np
import pandas as pd

from . import demo

_EMPTY = pd.Series(dtype=float, name="close")
_UA = "Mozilla/5.0 (compatible; edger-dashboard)"


def _demo_prices(ticker: str = demo.TICKER) -> pd.Series:
    rng = np.random.default_rng(demo.COMPANIES[ticker.upper()][1] + 4)
    idx = pd.bdate_range("2015-11-02", "2026-11-06")
    steps = rng.normal(0.0006, 0.017, len(idx))
    steps[(idx >= "2020-02-20") & (idx <= "2020-03-23")] -= 0.02  # a crash, for realism
    start = 18 * demo.COMPANIES[ticker.upper()][2] / 18e9  # scale with company size
    return pd.Series(start * np.exp(np.cumsum(steps)), index=idx, name="close")


def _years(period: str) -> int:
    return int(period[:-1]) if period.endswith("y") and period[:-1].isdigit() else 10


def _yahoo_history(ticker: str, period: str) -> pd.Series:
    try:
        import yfinance as yf

        hist = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=False)
    except Exception:
        return _EMPTY
    if hist is None or hist.empty or "Close" not in hist:
        return _EMPTY
    s = hist["Close"].dropna()
    s.index = pd.DatetimeIndex(s.index).tz_localize(None).normalize()
    return s.rename("close")


def stooq_symbol(ticker: str) -> str:
    # Stooq writes US share classes with a dash (BRK.B -> brk-b.us).
    return ticker.lower().replace(".", "-").replace("/", "-") + ".us"


def parse_stooq_csv(text: str) -> pd.Series:
    if not text or not text.lstrip().lower().startswith("date"):
        return _EMPTY  # "No data" or a rate-limit notice instead of CSV
    df = pd.read_csv(io.StringIO(text))
    if "Date" not in df or "Close" not in df:
        return _EMPTY
    s = pd.Series(pd.to_numeric(df["Close"], errors="coerce").values,
                  index=pd.to_datetime(df["Date"], errors="coerce"), name="close")
    return s[s.index.notna()].dropna().sort_index()


def _stooq_history(ticker: str) -> pd.Series:
    url = f"https://stooq.com/q/d/l/?s={stooq_symbol(ticker)}&i=d"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return parse_stooq_csv(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        return _EMPTY


def price_history(ticker: str, period: str = "10y") -> pd.Series:
    """Daily closing prices (tz-naive DatetimeIndex). Empty Series when every source fails."""
    if demo.is_demo(ticker):
        s = _demo_prices(ticker)
    else:
        s = _yahoo_history(ticker, period)
        if s.empty:
            s = _stooq_history(ticker)
    if s.empty:
        return _EMPTY
    return s[s.index >= s.index[-1] - pd.DateOffset(years=_years(period))]


def empty_quote() -> dict:
    return {"price": None, "prev_close": None, "change": None, "market_cap": None,
            "shares": None, "currency": "USD", "source": None}


def quote(ticker: str) -> dict:
    """Latest price, daily change, market cap and currency. Missing values are None.

    Price falls back from Yahoo's quote to Yahoo's recent history to Stooq. Market cap is
    only filled when Yahoo provides it (or its share count); callers compute it from SEC
    share counts otherwise.
    """
    out = empty_quote()
    if demo.is_demo(ticker):
        s = _demo_prices(ticker)
        out.update(price=float(s.iloc[-1]), prev_close=float(s.iloc[-2]), shares=1.2e9, source="예시")
        return _finish(out)

    try:
        import yfinance as yf

        fi = yf.Ticker(ticker).fast_info
    except Exception:
        fi = None
    if fi is not None:
        # Each field is a separate lazy lookup on Yahoo's side; one failing must not
        # discard the others.
        for key, field in (("price", "last_price"), ("prev_close", "previous_close"),
                           ("market_cap", "market_cap"), ("shares", "shares")):
            try:
                out[key] = _num(fi.get(field))
            except Exception:
                pass
        try:
            out["currency"] = fi.get("currency") or "USD"
        except Exception:
            pass
        if out["price"]:
            out["source"] = "Yahoo Finance"

    if out["market_cap"] is None:
        # ADRs (e.g. TSM) have no share count in fast_info; the full quote has the market cap.
        try:
            import yfinance as yf

            out["market_cap"] = _num((yf.Ticker(ticker).info or {}).get("marketCap"))
        except Exception:
            pass

    if not out["price"]:
        for name, history in (("Yahoo Finance", lambda: _yahoo_history(ticker, "5d")),
                              ("Stooq", lambda: _stooq_history(ticker))):
            s = history()
            if not s.empty:
                out["price"] = float(s.iloc[-1])
                out["prev_close"] = float(s.iloc[-2]) if len(s) > 1 else None
                out["source"] = name
                break
    return _finish(out)


def _finish(out: dict) -> dict:
    if out["price"] and out["prev_close"]:
        out["change"] = out["price"] / out["prev_close"] - 1
    if out["market_cap"] is None and out["price"] and out["shares"]:
        out["market_cap"] = out["price"] * out["shares"]
    return out


def _num(v) -> float | None:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(v) or v == 0 else v


# ---------------------------------------------------------------- dividends
def _demo_dividends(ticker: str) -> pd.Series:
    """Quarterly dividends since 2012, raised every year; DEMOB pays none (a growth stock)."""
    if ticker.upper() == "DEMOB":
        return pd.Series(dtype=float, name="dividend")
    rng = np.random.default_rng(demo.COMPANIES[ticker.upper()][1] + 9)
    dates = pd.date_range("2012-02-10", "2026-11-10", freq="QS-FEB") + pd.Timedelta(days=9)
    dates = dates[dates <= pd.Timestamp("2026-11-07")]
    amount, values, year = 0.20, [], None
    for d in dates:
        if year is not None and d.year != year:
            amount *= 1 + max(0.0, rng.normal(0.08, 0.03))
            if d.year == 2020:
                amount /= 1 + 0.08  # a frozen year, so the "increase streak" resets
        year = d.year
        values.append(round(amount, 3))
    return pd.Series(values, index=dates, name="dividend")


def dividends(ticker: str) -> tuple[pd.Series, bool]:
    """(per-payment dividends indexed by ex-date, ok). Split-adjusted.

    ``ok`` is False when the source failed, so an empty Series can be told apart from a
    company that simply pays no dividend.
    """
    if demo.is_demo(ticker):
        return _demo_dividends(ticker), True
    try:
        import yfinance as yf

        s = yf.Ticker(ticker).dividends
    except Exception:
        return pd.Series(dtype=float, name="dividend"), False
    if s is None:
        return pd.Series(dtype=float, name="dividend"), False
    s = s[s > 0].dropna()
    s.index = pd.DatetimeIndex(s.index).tz_localize(None).normalize()
    return s.sort_index().rename("dividend"), True


def fx_rate(from_currency: str, to_currency: str) -> float | None:
    """Units of ``to_currency`` per one ``from_currency`` (latest daily close), or None."""
    if not from_currency or not to_currency or from_currency == to_currency:
        return 1.0
    s = _yahoo_history(f"{from_currency}{to_currency}=X", "5d")
    return float(s.iloc[-1]) if not s.empty else None


# ---------------------------------------------------------------- quarterly financials
# Yahoo row name(s) -> dashboard metric key. First row present wins. Cash outflows are
# reported negative by Yahoo and flipped to positive amounts (as in SEC data).
_YAHOO_ROWS = {
    "income": {
        "revenue": ["Total Revenue", "Operating Revenue"],
        "gross_profit": ["Gross Profit"],
        "operating_income": ["Operating Income", "Total Operating Income As Reported"],
        "net_income": ["Net Income Common Stockholders", "Net Income"],
        "pretax_income": ["Pretax Income"],
        "income_tax": ["Tax Provision"],
        "interest_expense": ["Interest Expense", "Interest Expense Non Operating"],
        "shares_diluted": ["Diluted Average Shares"],
        "net_interest_income": ["Net Interest Income"],
    },
    "cashflow": {
        "ocf": ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"],
        "capex": ["Capital Expenditure", "Purchase Of PPE"],
        "da": ["Depreciation And Amortization", "Depreciation Amortization Depletion"],
        "dividends": ["Cash Dividends Paid", "Common Stock Dividend Paid"],
        "buybacks": ["Repurchase Of Capital Stock", "Common Stock Payments"],
    },
    "balance": {
        "cash": ["Cash And Cash Equivalents"],
        "assets": ["Total Assets"],
        "liabilities": ["Total Liabilities Net Minority Interest"],
        "equity": ["Stockholders Equity", "Common Stock Equity"],
        "current_assets": ["Current Assets"],
        "current_liabilities": ["Current Liabilities"],
        # Mapped onto the SEC debt components so the same debt logic applies:
        # noncurrent long-term debt + all current borrowings.
        "_ltd_noncurrent": ["Long Term Debt"],
        "_debt_current": ["Current Debt"],
        "_op_lease": ["Capital Lease Obligations"],
    },
}
_OUTFLOWS = {"capex", "dividends", "buybacks"}


def yahoo_quarterly(ticker: str) -> dict | None:
    """Recent quarterly financials from Yahoo (typically 5-7 quarters), for companies whose
    quarterly numbers are not in SEC XBRL (foreign filers). Returns {"raw": DataFrame indexed
    by quarter end with metric-key columns, "currency": reporting currency, "per_share_ok":
    bool} or None.

    Yahoo's share counts and EPS for ADRs are per ADR (TSM: 1 ADR = 5 shares) while SEC
    figures are per ordinary share, so per-share values are only kept when the reporting
    and trading currency agree.
    """
    if demo.is_demo(ticker):
        return None
    try:
        import yfinance as yf

        tk = yf.Ticker(ticker)
        frames = {"income": tk.quarterly_income_stmt, "cashflow": tk.quarterly_cashflow,
                  "balance": tk.quarterly_balance_sheet}
        info = tk.info or {}
    except Exception:
        return None
    columns: dict[str, pd.Series] = {}
    for kind, mapping in _YAHOO_ROWS.items():
        df = frames.get(kind)
        if df is None or df.empty:
            continue
        for key, names in mapping.items():
            for name in names:
                if name in df.index and df.loc[name].notna().any():
                    s = pd.to_numeric(df.loc[name], errors="coerce")
                    columns[key] = s.abs() if key in _OUTFLOWS else s
                    break
    if "revenue" not in columns and "net_income" not in columns:
        return None
    raw = pd.DataFrame(columns)
    raw.index = pd.DatetimeIndex(raw.index).tz_localize(None).normalize()
    raw = raw.sort_index()
    raw = raw[raw[[c for c in ("revenue", "net_income") if c in raw]].notna().any(axis=1)]
    if raw.empty:
        return None
    currency = info.get("financialCurrency") or info.get("currency") or "USD"
    per_share_ok = currency == (info.get("currency") or "USD")
    if not per_share_ok and "shares_diluted" in raw:
        raw["shares_diluted"] = np.nan
    if "shares_diluted" in raw and "net_income" in raw:
        raw["eps"] = raw["net_income"] / raw["shares_diluted"]  # NaN for ADRs (see above)
    return {"raw": raw, "currency": currency, "per_share_ok": per_share_ok}
