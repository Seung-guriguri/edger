"""Stock prices. SEC has no market data, so prices come from Yahoo Finance via yfinance.

Every function degrades to empty results instead of raising: Yahoo rate-limits and changes
its API from time to time, and the dashboard must keep working on SEC data alone.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import demo


def _demo_prices(ticker: str = demo.TICKER) -> pd.Series:
    rng = np.random.default_rng(demo.COMPANIES[ticker.upper()][1] + 4)
    idx = pd.bdate_range("2015-11-02", "2026-11-06")
    steps = rng.normal(0.0006, 0.017, len(idx))
    steps[(idx >= "2020-02-20") & (idx <= "2020-03-23")] -= 0.02  # a crash, for realism
    start = 18 * demo.COMPANIES[ticker.upper()][2] / 18e9  # scale with company size
    return pd.Series(start * np.exp(np.cumsum(steps)), index=idx, name="close")


def price_history(ticker: str, period: str = "10y") -> pd.Series:
    """Daily closing prices (tz-naive DatetimeIndex). Empty Series on failure."""
    if demo.is_demo(ticker):
        s = _demo_prices(ticker)
        years = int(period.rstrip("y")) if period.endswith("y") else 10
        return s[s.index >= s.index[-1] - pd.DateOffset(years=years)]
    try:
        import yfinance as yf

        hist = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=False)
    except Exception:
        return pd.Series(dtype=float, name="close")
    if hist is None or hist.empty or "Close" not in hist:
        return pd.Series(dtype=float, name="close")
    s = hist["Close"].dropna()
    s.index = pd.DatetimeIndex(s.index).tz_localize(None).normalize()
    return s.rename("close")


def quote(ticker: str) -> dict:
    """Latest price, daily change, market cap and currency. Missing values are None."""
    out = {"price": None, "prev_close": None, "change": None, "market_cap": None,
           "shares": None, "currency": "USD"}
    if demo.is_demo(ticker):
        s = _demo_prices(ticker)
        out.update(price=float(s.iloc[-1]), prev_close=float(s.iloc[-2]), shares=1.2e9)
    else:
        try:
            import yfinance as yf

            fi = yf.Ticker(ticker).fast_info
        except Exception:
            return out
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
